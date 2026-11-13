"""출력 가드: 모델 답을 코드 판정 결과(trace)와 대조해 구간·요약·가정·진료 안내·근거 표기를 코드가 보장한다."""
import json
import re

from src.guides.retrieval import guide_source, retrieve_guides


_ASSUMPTION_KEYS = (  # (판정 가정 문구의 시작, 답에 이 단어들이 모두 있으면 이미 밝힌 것으로 본다)
    ("mmol/L", ("환산",)), ("공복 가정", ("공복", "가정")), ("성별 미입력", ("남", "여", "기준")))


def collect_assumptions(trace: list) -> list[str]:
    """trace의 judge_checkup_item 결과에서 환산·공복 가정·성별 미입력 문구를 중복 없이 모은다."""
    found: list[str] = []
    for step in trace:
        if step.get("step") != "judge_checkup_item":
            continue
        try:
            res = json.loads(step["output"])
        except (TypeError, ValueError):
            continue
        for a in res.get("assumptions", []):
            if any(a.startswith(k) or k in a for k, _ in _ASSUMPTION_KEYS) and a not in found:
                found.append(a)
    return found


_BAND_RE = re.compile(r"질환\s?의심|경계|(?<!비)정상")
_HOLD_WORDS = ("보류", "판정할 수 없", "판정하지", "판정 불가", "판정이 어렵")


def _norm_band(word: str) -> str:
    return "질환의심" if word.startswith("질환") else word


def _expected_bands(r: dict) -> set:
    """판정 결과가 허용하는 구간 집합. 보류면 빈 집합."""
    if r.get("status") != "판정":
        return set()
    bands = {r.get("band")} | {v.get("band") for v in r.get("by_sex", {}).values()
                               if v.get("status") == "판정"}
    return {b for b in bands if b}


def _correct_line(r: dict) -> str:
    """코드 판정 결과로 만든 항목 한 줄."""
    unit = r.get("unit") or ""
    if r.get("status") != "판정":
        return f"- {r['item']} {r.get('value')}{unit}: 판정 보류 ({r.get('reason', '')})"
    if r.get("by_sex"):
        parts = [f"{s} 기준 {v['band']}" for s, v in r["by_sex"].items() if v.get("status") == "판정"]
        return f"- {r['item']} {r['value']:g}{unit}: " + ", ".join(parts)
    return f"- {r['item']} {r['value']:g}{unit}: {r['band']}"


def _item_names(r: dict) -> list[str]:
    name = str(r.get("item", ""))
    names = {name, name.replace(" ", "")}
    if name.endswith(" 혈압"):
        names.add(name.split()[0])
    return [n for n in names if n]


def ensure_band_consistency(answer: str, trace: list) -> str:
    """출력 가드: 답의 항목별 구간 표기를 trace의 judge_checkup_item 결과와 대조한다.

    불일치하거나 보류 항목에 구간을 쓴 줄은 코드 판정 결과 한 줄로 바꾼다.
    """
    latest: dict[str, dict] = {}
    for r in _judge_results(trace):
        latest[str(r.get("item"))] = r  # 같은 항목을 여러 번 판정했으면 마지막 결과
    if not latest:
        return answer
    out = []
    for line in answer.split("\n"):
        words = {_norm_band(w) for w in _BAND_RE.findall(line)}
        hits = [r for r in latest.values() if any(n in line for n in _item_names(r))]
        if not words or not hits:
            out.append(line)
            continue
        allowed = set().union(*(_expected_bands(r) for r in hits))
        # 기준 구간 설명이 함께 있는 줄은 실제 구간이 들어 있으면 유지한다
        bad = not (words & allowed) if allowed else not any(w in line for w in _HOLD_WORDS)
        if bad:
            out.extend(_correct_line(r) for r in hits)
        else:
            out.append(line)
    return "\n".join(out)


def ensure_assumptions(answer: str, trace: list) -> str:
    """판정에 쓴 환산값·공복 가정·남녀 기준 모두 제시를 답이 빠뜨렸으면 코드로 덧붙인다."""
    missing = []
    for a in collect_assumptions(trace):
        words = next(w for k, w in _ASSUMPTION_KEYS if k in a)
        stated = all(w in answer for w in words)
        if "환산" in words:  # 환산은 환산된 값(mg/dL)까지 답에 있어야 밝힌 것으로 본다
            stated = stated and a.split("=")[-1].strip().split()[0] in answer
        if not stated:
            missing.append(a)
    if not missing:
        return answer
    return answer + "\n\n[판정 가정] " + " / ".join(missing)


_FASTING_STATED_RE = re.compile(r"금식|굶|공복\s?(상태|으로|에)|아침[을은]?\s?(안|못)\s?먹|\d+\s?시간\s?(이상\s?)?(동안\s?)?(안\s?먹|공복|금식)")
FASTING_ASSUMPTION = "공복(8시간 이상 금식) 상태로 가정하고 판정했습니다."


def user_stated_fasting(question: str) -> bool:
    """질문에 금식·공복 상태를 따로 말한 표현이 있는지 본다. 항목명 '공복혈당'만으로는 공복을 확정한 것으로 보지 않는다."""
    return bool(_FASTING_STATED_RE.search(question.replace("공복혈당", "")))


def ensure_fasting_assumption(answer: str, question: str, trace: list) -> str:
    """공복혈당을 판정했는데 사용자가 공복 상태를 말하지 않았으면 '공복 가정' 문장을 코드로 덧붙인다.

    모델이 fasting=true로 넘겼어도 도구 가정에 안 남으므로 코드가 직접 확인한다. 이미 답에 공복·가정이 있으면 덧붙이지 않는다.
    """
    judged = any(r.get("item") == "공복혈당" and r.get("status") == "판정" for r in _judge_results(trace))
    if not judged or user_stated_fasting(question) or ("공복" in answer and "가정" in answer):
        return answer
    return answer + "\n\n[판정 가정] " + FASTING_ASSUMPTION


NO_GUIDE = "근거 지침 없음"
_GUIDE_WORDS = ("지침", "생활습관", "관리", "식습관", "운동", "음식", "어떻게", "줄이", "개선")
# 항목을 특정하지 않아도 생활습관을 직접 묻는 말 (예: "식습관 지침")
_LIFESTYLE_WORDS = ("지침", "생활습관", "식습관", "운동", "음식")
# 지침 문서별 주제 단어: 질문이나 판정 항목에 이 단어가 있어야 그 문서 조각을 근거로 쓴다
_GUIDE_TOPICS = {
    "blood_pressure.md": ("혈압",),
    "blood_sugar.md": ("혈당", "당뇨"),
    "lipids.md": ("콜레스테롤", "중성지방", "지질", "HDL", "LDL"),
    "obesity.md": ("체질량지수", "BMI", "비만", "체중", "몸무게", "허리둘레", "복부"),
    "liver.md": ("간 기능", "간기능", "간수치", "간 수치", "AST", "ALT", "감마", "지티피", "GTP", "지방간"),
    "anemia.md": ("혈색소", "빈혈", "헤모글로빈"),
}


def _relevant_guides(question: str, judged: list[dict]) -> set:
    """질문과 판정 항목 이름에 나온 주제 단어로 관련 지침 문서 파일명을 고른다."""
    text = question + " " + " ".join(str(r.get("item", "")) for r in judged)
    return {name for name, words in _GUIDE_TOPICS.items() if any(w in text for w in words)}


def _keep_relevant(contexts: list, topics: set, lifestyle: bool) -> list:
    """관련 없는 지침 조각을 근거에서 뺀다 (예: 갑상선·위암 검진 질문에 혈압 지침이 붙는 문제).

    주제를 알 수 있으면 그 문서 조각만 남기고, 주제 없이 생활습관만 물으면 그대로 두고,
    둘 다 아니면(다루지 않는 검사 등) 모두 뺀다.
    """
    if topics:
        return [c for c in contexts if not (isinstance(c, dict) and "doc_id" in c)
                or c["doc_id"].split("#")[0].split("/")[-1] in topics]
    return list(contexts) if lifestyle else []


def _judge_results(trace: list) -> list[dict]:
    """trace에서 judge_checkup_item 결과(JSON)만 꺼낸다."""
    out = []
    for step in trace:
        if step.get("step") == "judge_checkup_item":
            try:
                out.append(json.loads(step["output"]))
            except (TypeError, ValueError):
                pass
    return out


def _fmt_value(v) -> str:
    """입력값을 군더더기 없는 숫자 문자열로 만든다 (예: 110.0 → 110)."""
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _summary_items(trace: list) -> list[dict]:
    """trace의 judge_checkup_item·calc_bmi 결과를 요약 단위로 정규화한다.

    (항목, 값, 성별)이 같은 결과는 하나로 합치고, 성별이 다르거나 값이 다른 결과는 각각 남긴다.
    성별 결과는 by_sex에서 오거나 결과의 sex 필드(성별 지정 호출)에서 온다.
    """
    bmi_calc = next((b["bmi"] for b in reversed([_loads(x) for x in trace if x.get("step") == "calc_bmi"])
                     if b.get("bmi") is not None), None)
    seen: dict[tuple, dict] = {}
    for r in _judge_results(trace):
        subs = [(sx, v) for sx, v in r["by_sex"].items()] if r.get("by_sex") else [(r.get("sex"), r)]
        for sex, v in subs:
            value = v.get("value", r.get("value"))
            key = (r.get("item"), float(value) if isinstance(value, (int, float)) else value, sex)
            if key not in seen:
                seen[key] = {"item": str(r.get("item", "")), "value": value, "unit": v.get("unit") or r.get("unit") or "",
                             "sex": sex, "status": v.get("status", r.get("status")), "band": v.get("band"),
                             "range_text": v.get("range") or v.get("range_note") or "",
                             "reason": v.get("reason", r.get("reason", "")), "bmi": None}
                if seen[key]["item"] == "체질량지수" and bmi_calc is not None:
                    seen[key]["bmi"] = bmi_calc
    return list(seen.values())


def _summary_line(e: dict) -> str:
    """요약 단위 하나를 항목 이름·입력값·단위·구간·기준 원문 표기가 든 한 줄로 만든다."""
    tag = f" ({e['sex']} 기준)" if e["sex"] else ""
    head = f"- {e['item']}{tag} {_fmt_value(e['value'])}{e['unit']}"
    if e["status"] != "판정":
        return f"{head}: 판정 보류 ({e['reason']})"
    calc = f" (계산값 {e['bmi']:g})" if e["bmi"] is not None else ""
    fast = " (공복 기준 수치로 판정)" if e["item"] == "공복혈당" else ""
    return f"{head}{calc}: {e['band']} 구간 (기준 {e['range_text']}){fast}"


def _has_number(line: str, value) -> bool:
    """줄에 값이 숫자 경계 기준으로 정확히 있는지 확인한다 (예: 12는 120과 일치하지 않는다)."""
    if not isinstance(value, (int, float)):
        return str(value) in line
    return re.search(r"(?<![\d.])" + re.escape(f"{value:g}") + r"(?:\.0+)?(?!\d|\.\d)", line) is not None


def _line_covers(line: str, e: dict) -> bool:
    """모델이 쓴 줄이 요약 줄을 대신할 수 있는지: 이름·값·구간·기준 표기·성별·공복 문구가 모두 있어야 한다."""
    if not any(n in line for n in _item_names({"item": e["item"]})) or not _has_number(line.replace(e["range_text"], " ") if e["range_text"] else line, e["value"]):
        return False
    if e["status"] != "판정":
        return any(w in line for w in _HOLD_WORDS)
    if e["band"] not in line or e["range_text"] not in line or (e["unit"] and e["unit"] not in line):
        return False
    if e["sex"] and not re.search(rf"(?<![가-힣]){e['sex']}(?:성|자)?(?![가-힣])", line):
        return False
    return e["item"] != "공복혈당" or "공복 기준" in line


def ensure_summary(answer: str, trace: list) -> str:
    """판정 요약 한 줄을 코드가 보장한다: 결과마다 요약 줄이 답에 없으면 판정 도구 결과로 만든 줄을 덧붙인다."""
    lines = answer.split("\n")
    missing = [_summary_line(e) for e in _summary_items(trace) if not any(_line_covers(l, e) for l in lines)]
    if not missing:
        return answer
    return answer + "\n\n[판정 요약]\n" + "\n".join(missing)


def _loads(step: dict) -> dict:
    """trace 단계의 output(JSON)을 dict로 읽고, 실패하면 빈 dict를 돌려준다."""
    try:
        return json.loads(step["output"])
    except (TypeError, ValueError, KeyError):
        return {}


def _flagged_items(results: list[dict]) -> list[str]:
    """경계·질환의심 판정(성별별 포함)이 나온 항목 이름."""
    items = []
    for r in results:
        bands = [r.get("band")] + [v.get("band") for v in r.get("by_sex", {}).values()]
        if any(b in ("경계", "질환의심") for b in bands) and r["item"] not in items:
            items.append(r["item"])
    return items


def ensure_evidence(answer: str, question: str, contexts: list, trace: list) -> tuple[str, list]:
    """근거 표기를 코드로 보장한다: 판정 기준 출처, 지침 contexts·출처, 검색 0건이면 '근거 지침 없음'."""
    judged = [r for r in _judge_results(trace) if r.get("status") == "판정"]
    flagged = _flagged_items(judged)
    topics = _relevant_guides(question, judged)
    lifestyle = any(w in question for w in _LIFESTYLE_WORDS)
    searchable = bool(topics) or lifestyle  # 주제를 알 수 없는 질문(다루지 않는 검사 등)은 지침을 찾지 않는다
    asks_guide = searchable and any(w in question for w in _GUIDE_WORDS)
    contexts = _keep_relevant(contexts, topics, lifestyle)
    notes = []
    if (flagged or asks_guide) and not contexts:  # 모델이 검색을 빠뜨렸으면 코드가 직접 검색한다
        query = " ".join(flagged) + " " + question if flagged else question
        try:
            chunks, _ = retrieve_guides(query)
        except Exception:
            chunks = []
        contexts = _keep_relevant([{"doc_id": c["doc_id"], "text": c["text"]} for c in chunks], topics, lifestyle)
        trace.append({"step": "retrieve_guides", "input": query, "output": f"문서 {len(contexts)}건 (코드 보충 검색)"})
    if judged:
        src, base = judged[0]["source"], judged[0]["base_date"]
        if src not in answer or base not in answer:
            notes.append(f"[판정 기준 출처] {src}, 기준일 {base}")
    if contexts:
        ids = list(dict.fromkeys(c["doc_id"] for c in contexts if isinstance(c, dict) and "doc_id" in c))
        missing = [d for d in ids if d not in answer]
        if missing:
            notes.append("[지침 출처] " + " / ".join(guide_source(d) for d in missing))
    elif flagged or asks_guide:
        if NO_GUIDE not in answer:
            notes.append(f"[지침] {NO_GUIDE}: 검색된 지침이 없어 생활습관 지침은 안내하지 않습니다.")
    return (answer + "\n\n" + "\n".join(notes) if notes else answer), contexts


REFERRAL_NOTICE = "질환의심 판정이 있는 항목은 가까운 의료기관(내과·가정의학과 등)에서 진료와 정밀 검사를 받아 보시길 권합니다."
_REFERRAL_WORDS = ("의료기관", "병원", "의원", "진료", "의료진")


def _has_suspect(node) -> bool:
    """판정 결과(중첩 구조 포함)에 질환의심 구간이 있는지 확인한다."""
    if isinstance(node, dict):
        return node.get("band") == "질환의심" or any(_has_suspect(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_suspect(v) for v in node)
    return False


def ensure_referral(answer: str, trace: list) -> str:
    """G3: 질환의심 판정이 하나라도 있는데 답에 진료 안내가 없으면 코드로 덧붙인다."""
    suspect = False
    for step in trace:
        if step.get("step") != "judge_checkup_item":
            continue
        try:
            suspect = suspect or _has_suspect(json.loads(step["output"]))
        except (TypeError, ValueError):
            continue
    if not suspect or any(w in answer for w in _REFERRAL_WORDS):
        return answer
    return answer + "\n\n" + REFERRAL_NOTICE


UNSUPPORTED_REASON = "지원하지 않는 검사 항목입니다."


def ensure_unsupported_notice(answer: str, trace: list) -> str:
    """지원하지 않는 검사 항목으로 보류된 항목이 있으면 범위 밖 안내와 검진 기관 상담 권유를 덧붙인다.

    모델 문장은 지우지 않고, 이미 항목 이름과 안내가 모두 답에 있으면 덧붙이지 않는다.
    """
    items = []
    for r in _judge_results(trace):
        name = str(r.get("item", "")).strip()
        if r.get("reason") == UNSUPPORTED_REASON and name and name not in items:
            items.append(name)
    if not items:
        return answer
    missing = [i for i in items if i not in answer]
    if not missing and "다루지 않는 검사" in answer and "검진 기관" in answer:
        return answer
    return (answer + "\n\n[범위 밖 안내] " + ", ".join(items) + "은(는) 이 서비스에서 다루지 않는 검사입니다. "
            "결과 해석은 검진 기관(검진을 받은 병원)에 상담해 주시길 권합니다.")


_TOOL_STEPS = ("judge_checkup_item", "calc_bmi", "retrieve_guides")
FIXED_ANSWER = (
    "이 서비스는 건강검진 수치 중 수축기 혈압, 이완기 혈압, 공복혈당, 총콜레스테롤, 중성지방, HDL 콜레스테롤, "
    "LDL 콜레스테롤, 체질량지수, 허리둘레, AST, ALT, 감마지티피, 혈색소 13개 항목만 판정합니다. "
    "영상 검진(X선·CT·초음파)이나 암 검진 같은 검사는 다루지 않는 검사라서 이 서비스에서 해석해 드릴 수 없습니다. "
    "판정을 원하시면 위 항목의 수치(단위 포함)를 입력해 주세요. "
    "그 밖의 검사 결과는 검진 기관(검진을 받은 병원)에 상담해 주시길 권합니다.")


def ensure_scope_answer(answer: str, trace: list) -> tuple[str, bool]:
    """도구 호출이 하나도 없는 답은 모델 문장에 근거가 없으므로 코드가 정한 고정 문장으로 통째로 바꾼다.

    바꿨으면 trace에 fixed_answer 단계를 남기고 (고정 문장, True)를, 아니면 (원래 답, False)를 돌려준다.
    """
    if any(step.get("step") in _TOOL_STEPS for step in trace):
        return answer, False
    trace.append({"step": "fixed_answer", "input": "도구 호출 없음", "output": "모델 답을 고정 문장(범위 밖·수치 없음 안내)으로 대체"})
    return FIXED_ANSWER, True
