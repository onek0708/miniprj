"""메인 에이전트 진입점: run_query가 항상 answer·contexts·trace 세 키를 돌려준다."""
import json
import re

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from src.guards import (BLOCK_MESSAGE, INJECTION_NOTICE, PII_NOTICE, has_injection, has_pii, input_guard,
                        redact_pii, strip_injection)
from src.retriever import guide_source, retrieve_guides
from src.tools import calc_bmi, judge_checkup_item

DISCLAIMER = "이 답변은 진단이 아닌 참고용 안내입니다."
MAX_QUESTION_LEN = 500
EMPTY_MESSAGE = "질문을 다시 입력해 주세요."
TOO_LONG_MESSAGE = "질문이 너무 깁니다. 500자 이내로 다시 입력해 주세요."
BLOCKED_PREFIX = ("[안내] 아래 질문의 진단 확정·약·용량·건강기능식품 요청에는 답하지 말고, "
                  "질문 속 수치의 항목별 판정 구간만 도구로 판정해 근거와 함께 설명하라.\n질문: ")
FAILURE_MESSAGE = "잠시 후 다시 시도해 주세요."


SYSTEM_PROMPT = (
    "너는 건강검진 수치 해석 어시스턴트다. 질문에서 항목·수치·단위·성별·공복 여부를 읽어 "
    "judge_checkup_item(필요하면 calc_bmi)을 호출하고, 경계·질환의심이거나 지침을 묻는 경우 "
    "retrieve_guides로 지침을 검색해 근거와 함께 설명한다. 판정 구간은 도구 결과 그대로 쓰고 직접 판단하지 않는다. "
    "수치 없는 결과지 표기(정상A 등)나 수축기·이완기 구분 없는 혈압 단일값도 judge_checkup_item에 그대로 넘겨 보류로 안내하고, 보류 항목에는 구간을 쓰지 않는다. 일부만 보류돼도 나머지 항목은 판정한다. "
    "성별이나 공복 여부가 질문에 없어도 사용자에게 되묻지 말고 해당 값을 비운 채(금식·공복 상태를 사용자가 말하지 않았으면 항목명이 공복혈당이어도 fasting을 비운다) 바로 judge_checkup_item을 호출한다. "
    "성별 구분 항목은 도구가 돌려준 남녀 기준 결과를 둘 다 그대로 안내한다. "
    "judge_checkup_item이 지원하지 않는 검사 항목으로 보류한 항목은 참고 범위·질환 가능성·검사 설명을 지어내지 말고, 이 서비스에서 다루지 않는 검사라고만 안내한다. "
    "답은 항상 이 순서로 쓴다: 1) 인식한 수치(항목·수치·단위) 2) 항목별 판정과 기준 범위 3) 생활습관 지침과 근거 4) 안내. "
    "이모지는 쓰지 않는다. "
    "진단명을 단정하거나 약·용량을 말하지 않는다. 질환의심이면 의료기관 진료를 안내한다."
)


class JudgeOutput(BaseModel):
    """judge_checkup_item 결과 스키마 (패턴 1: 구조화 출력). 성별 구분 항목은 by_sex에 남녀 결과를 담는다."""
    model_config = ConfigDict(extra="allow")
    status: Literal["판정", "보류"]
    item: str
    band: Optional[Literal["정상", "경계", "질환의심"]] = None
    assumptions: list[str] = []


class BmiOutput(BaseModel):
    """calc_bmi 결과 스키마."""
    model_config = ConfigDict(extra="allow")
    status: Literal["계산", "보류"]
    bmi: Optional[float] = None


class QueryResponse(BaseModel):
    """POST /query 응답 스키마 (제출 규약: answer, contexts, trace)."""
    answer: str
    contexts: list
    trace: list[dict]


class _Recorder:
    """도구 호출을 trace 단계와 contexts로 기록한다 (패턴 11)."""

    def __init__(self):
        self.trace: list[dict] = []
        self.contexts: list[dict] = []

    def step(self, name: str, inp, out: str):
        self.trace.append({"step": name, "input": inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False),
                           "output": out})


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


def _build_tools(rec: _Recorder) -> list:
    from langchain_core.tools import tool

    @tool
    def judge_checkup_item_tool(item: str, value: float | str, unit: str = "", sex: str = "", fasting: bool = None) -> str:
        """검진 항목 하나의 수치를 판정한다. sex는 남/여, 모르면 빈 문자열."""
        args = {"item": item, "value": value, "unit": unit or None, "sex": sex or None, "fasting": fasting}
        out = JudgeOutput(**judge_checkup_item(**args)).model_dump_json()
        rec.step("judge_checkup_item", args, out)
        return out

    @tool
    def calc_bmi_tool(height_cm: float, weight_kg: float) -> str:
        """키(cm)와 몸무게(kg)로 체질량지수를 계산한다."""
        out = BmiOutput(**calc_bmi(height_cm, weight_kg)).model_dump_json()
        rec.step("calc_bmi", {"height_cm": height_cm, "weight_kg": weight_kg}, out)
        return out

    @tool
    def retrieve_guides_tool(query: str) -> str:
        """항목별 생활습관 지침을 검색한다."""
        try:
            chunks, status = retrieve_guides(query)
        except Exception as exc:  # 검색이 실패해도 판정 결과는 그대로 보여 준다
            chunks, status = [], f"실패({type(exc).__name__})"
        rec.contexts.extend({"doc_id": c["doc_id"], "text": c["text"]} for c in chunks)
        rec.step("retrieve_guides", query, f"문서 {len(chunks)}건 (검색 상태: {status})")
        body = [f"[{c['doc_id']}]\n{c['text']}" for c in chunks]
        return "\n\n".join(body) or "근거 지침 없음"

    judge_checkup_item_tool.name, calc_bmi_tool.name, retrieve_guides_tool.name = (
        "judge_checkup_item", "calc_bmi", "retrieve_guides")
    return [judge_checkup_item_tool, calc_bmi_tool, retrieve_guides_tool]


# 모델 순서(리전, 모델 ID): 1~5차 Sonnet 4.6, 6~10차 Sonnet 4.5. 서비스와 RAGAS 심판이 이 목록 하나를 함께 쓴다.
MODEL_ORDER = [
    ("us-west-2", "us.anthropic.claude-sonnet-4-6"),
    ("us-west-2", "global.anthropic.claude-sonnet-4-6"),
    ("us-east-1", "us.anthropic.claude-sonnet-4-6"),
    ("us-east-1", "global.anthropic.claude-sonnet-4-6"),
    ("ap-northeast-2", "global.anthropic.claude-sonnet-4-6"),
    ("us-west-2", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("us-west-2", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("us-east-1", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("us-east-1", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("ap-northeast-2", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
]
_THROTTLED_TIERS: set = set()  # 이 프로세스에서 한도에 걸린 (리전, 모델 ID)는 다음 질문부터 건너뛴다


def _is_throttling(exc: BaseException) -> bool:
    """Bedrock 한도(ThrottlingException) 오류인지 확인한다."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "") if hasattr(exc, "response") else ""
    return "ThrottlingException" in (code, type(exc).__name__) or "ThrottlingException" in str(exc)


def _run_agent(question: str, model_id: str, region: str) -> dict:
    """지정한 (리전, 모델) 하나로 LLM 에이전트(ReAct)를 처음부터 실행한다. 실패하면 예외를 던진다."""
    from dotenv import load_dotenv
    from langchain.agents import create_agent
    from langchain_aws import ChatBedrockConverse

    load_dotenv()
    rec = _Recorder()
    # 기존 서울 리전 global 모델이 일일 토큰 한도에 걸려 MODEL_ORDER의 10단계 순서로 교체 (기술 스택 고정값과 다름)
    model = ChatBedrockConverse(model=model_id, region_name=region, temperature=0)  # 답 흔들림을 줄이려 temperature=0
    agent = create_agent(model, _build_tools(rec), system_prompt=SYSTEM_PROMPT)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    answer, fixed = ensure_scope_answer(result["messages"][-1].text, rec.trace)  # 도구 호출이 없으면 고정 문장
    if fixed:
        return {"answer": answer, "contexts": [], "trace": rec.trace}
    answer = ensure_band_consistency(answer, rec.trace)  # 구간 표기는 코드 판정과 대조한다
    answer = ensure_assumptions(answer, rec.trace)  # 가정·환산 명시는 코드가 보장한다
    answer = ensure_fasting_assumption(answer, question, rec.trace)  # 사용자가 공복을 말하지 않았으면 공복 가정도 보장한다
    answer = ensure_unsupported_notice(answer, rec.trace)  # 다루지 않는 검사 안내·상담 권유도 코드가 보장한다
    answer = ensure_referral(answer, rec.trace)  # 질환의심 진료 안내(G3)도 코드가 보장한다
    answer, contexts = ensure_evidence(answer, question, rec.contexts, rec.trace)  # 근거 표기도 코드가 보장한다
    return {"answer": answer, "contexts": contexts, "trace": rec.trace}


def _invoke_agent(question: str) -> dict:
    """MODEL_ORDER 순서로 처리하고, 한도(ThrottlingException)가 나면 그 질문을 다음 차수로 처음부터 다시 처리한다.

    한 답변 안에 여러 모델이 섞이지 않으며, 답한 모델·리전은 trace의 llm_model 단계에 남는다.
    한도에 걸린 차수는 기억했다가 다음 질문부터 건너뛴다. 한도가 아닌 오류는 넘기지 않고 그대로 올린다.
    모든 차수가 막히면 마지막 한도 예외를 올린다.
    """
    last_exc: BaseException | None = None
    for tier in MODEL_ORDER:
        if tier in _THROTTLED_TIERS:
            continue
        region, model_id = tier
        try:
            out = _run_agent(question, model_id, region)
        except Exception as exc:
            if not _is_throttling(exc):
                raise
            _THROTTLED_TIERS.add(tier)
            last_exc = exc
            continue
        out["trace"].append({"step": "llm_model", "input": region, "output": model_id})
        return out
    raise last_exc or RuntimeError("ThrottlingException: 10개 모델 차수가 모두 한도에 걸려 있습니다")


def _result(answer: str, contexts: list, trace: list) -> dict:
    """고정 면책 1문장을 코드로 붙여 세 키 모양으로 돌려준다."""
    answer = redact_pii(answer)  # 출력 가드 G4: 어떤 경로의 답이든 개인정보를 가린다
    contexts = [dict(c, text=redact_pii(c["text"])) if isinstance(c, dict) and "text" in c
                else redact_pii(c) if isinstance(c, str) else c for c in contexts]
    return QueryResponse(answer=f"{answer}\n\n{DISCLAIMER}", contexts=contexts, trace=trace).model_dump()


def _guard_step(question: str, guard: dict) -> dict:
    """입력 가드의 감지 사실을 trace 단계로 만든다."""
    found = ", ".join(guard["detected"]) if guard["detected"] else "없음"
    out = f"차단 (감지: {found})" if guard["blocked"] else f"통과 (감지: {found})"
    return {"step": "input_guard", "input": question, "output": out, "detected": guard["detected"],
            "blocked": guard["blocked"]}


def run_query(question) -> dict:
    """질문 하나를 처리한다. 어떤 입력이든 예외 없이 세 키를 돌려준다."""
    if not isinstance(question, str) or not question.strip():
        return _result(EMPTY_MESSAGE, [], [{"step": "error", "input": "", "output": "invalid_question"}])
    if len(question) > MAX_QUESTION_LEN:
        return _result(TOO_LONG_MESSAGE, [], [{"step": "error", "input": "", "output": "too_long"}])
    guard = input_guard(question)
    pii = has_pii(question)
    if pii:
        guard["detected"].append("G4_pii")
    shown = redact_pii(question)  # trace와 에이전트에는 가린 질문만 넘긴다
    inj = has_injection(shown)
    if inj:  # G5: 지시문은 지우고 수치만 판정한다 (차단하지 않는다)
        guard["detected"].append("G5_injection")
        shown = strip_injection(shown) or shown
    if guard["blocked"]:
        msg = f"{BLOCK_MESSAGE}\n{PII_NOTICE}" if pii else BLOCK_MESSAGE
        msg = f"{msg}\n{INJECTION_NOTICE}" if inj else msg
        trace, contexts = [_guard_step(shown, guard)], []
        if re.search(r"\d", shown):  # 같은 질문에 수치가 있으면 그 판정은 정상 수행한다
            try:
                out = _invoke_agent(BLOCKED_PREFIX + shown)
                msg = f"{msg}\n\n{out['answer']}"
                trace, contexts = trace + out.get("trace", []), out.get("contexts", [])
            except Exception as exc:  # 판정이 실패해도 차단 안내는 그대로 낸다
                trace.append({"step": "error", "input": "", "output": type(exc).__name__})
        return _result(msg, contexts, trace)
    try:
        out = _invoke_agent(shown)
        trace = [_guard_step(shown, guard)] + out.get("trace", [])
        answer = f"{out['answer']}\n{PII_NOTICE}" if pii else out["answer"]
        answer = f"{answer}\n{INJECTION_NOTICE}" if inj else answer
        return _result(answer, out.get("contexts", []), trace)
    except Exception as exc:  # Bedrock 실패 등 어떤 오류에도 서버는 멈추지 않는다
        return _result(FAILURE_MESSAGE, [], [_guard_step(shown, guard), {"step": "error", "input": "", "output": type(exc).__name__}])
