"""판정 요약 한 줄 보장: 항목 이름·입력값·단위·구간·기준 원문 표기가 한 줄에 있다 (실제 Bedrock 호출 없음)."""
import json

from src import agent
from src.tools import calc_bmi, judge_checkup_item


def _trace(*results, bmi=None):
    t = [{"step": "judge_checkup_item", "input": "{}", "output": json.dumps(r, ensure_ascii=False)} for r in results]
    if bmi:
        t.append({"step": "calc_bmi", "input": "{}", "output": json.dumps(bmi)})
    return t


def _has_line(text, *words):
    return any(all(w in line for w in words) for line in text.split("\n"))


def test_summary_added_when_answer_has_no_such_line():
    r = judge_checkup_item("공복혈당", 110, "mg/dL")
    out = agent.ensure_summary("공복혈당이 100 ~ 125 사이라 경계입니다.", _trace(r))
    assert _has_line(out, "공복혈당", "110", "mg/dL", "경계", "100 이상 126 미만", "공복 기준")


def test_table_style_answer_gets_one_line_summary():
    r = judge_checkup_item("총콜레스테롤", 210, "mg/dL")
    ans = "| 항목 | 값 | 구간 |\n|---|---|---|\n| 총콜레스테롤 | 210 | 경계 |"
    out = agent.ensure_summary(ans, _trace(r))
    assert _has_line(out, "총콜레스테롤", "210", "mg/dL", r["band"], r["range"])


def test_existing_complete_line_is_not_duplicated():
    r = judge_checkup_item("총콜레스테롤", 210, "mg/dL")
    ans = f"총콜레스테롤 210 mg/dL: {r['band']} (기준 {r['range']})"
    assert agent.ensure_summary(ans, _trace(r)) == ans


def test_fasting_wording_required_for_glucose():
    r = judge_checkup_item("공복혈당", 90, "mg/dL")
    ans = f"공복혈당 90 mg/dL: {r['band']} (기준 {r['range']})"
    out = agent.ensure_summary(ans, _trace(r))
    assert "공복 기준 수치로 판정" in out


def test_normal_item_also_gets_summary():
    r = judge_checkup_item("수축기 혈압", 110, "mmHg")
    out = agent.ensure_summary("괜찮습니다.", _trace(r))
    assert _has_line(out, "수축기 혈압", "110", "mmHg", "정상", r["range"])


def test_sex_split_item_gets_line_per_sex():
    r = judge_checkup_item("혈색소", 12, "g/dL")
    out = agent.ensure_summary("남녀 기준이 다릅니다.", _trace(r))
    assert _has_line(out, "혈색소", "남 기준", "12", "g/dL", "경계", "12 이상 13 미만")
    assert _has_line(out, "혈색소", "여 기준", "12", "g/dL", "정상", "12 이상 15.6 미만")


def test_bmi_line_has_calculated_value_and_band():
    b = calc_bmi(170, 79.2)
    r = judge_checkup_item("체질량지수", b["bmi"])
    out = agent.ensure_summary("비만입니다.", _trace(r, bmi=b))
    assert _has_line(out, "체질량지수", f"{b['bmi']:g}", "계산값", r["band"], r["range"])


def test_hold_item_line_has_reason_without_band():
    r = judge_checkup_item("폴산", 3)
    out = agent.ensure_summary("알 수 없습니다.", _trace(r))
    assert _has_line(out, "폴산", "판정 보류", r["reason"])
    summary = out.split("[판정 요약]")[1]
    assert not agent._BAND_RE.search(summary)


def test_hold_item_already_stated_is_kept():
    r = judge_checkup_item("폴산", 3)
    ans = "폴산 3은 판정 보류입니다."
    assert agent.ensure_summary(ans, _trace(r)) == ans


def test_summary_band_always_matches_tool_result_after_band_consistency():
    r = judge_checkup_item("공복혈당", 130, "mg/dL")
    ans = agent.ensure_band_consistency("공복혈당 130 mg/dL는 정상입니다.", _trace(r))
    out = agent.ensure_summary(ans, _trace(r))
    assert "정상" not in out and _has_line(out, "공복혈당", "130", "질환의심", r["range"])


def test_no_judge_results_leaves_answer_unchanged():
    assert agent.ensure_summary("안녕하세요", []) == "안녕하세요"


def test_sex_specified_calls_give_one_tagged_line_each():
    rm = judge_checkup_item("혈색소", 12, "g/dL", sex="남")
    rf = judge_checkup_item("혈색소", 12, "g/dL", sex="여")
    out = agent.ensure_summary("혈색소 결과입니다.", _trace(rm, rf))
    assert _has_line(out, "혈색소", "남 기준", "12", rm["band"], rm["range"])
    assert _has_line(out, "혈색소", "여 기준", "12", rf["band"], rf["range"])


def test_model_line_without_sex_tag_is_not_accepted():
    rm = judge_checkup_item("혈색소", 12, "g/dL", sex="남")
    ans = f"혈색소 12 g/dL: {rm['band']} (기준 {rm['range']})"
    assert "[판정 요약]" in agent.ensure_summary(ans, _trace(rm))
    ok = f"혈색소 (남성) 12 g/dL: {rm['band']} (기준 {rm['range']})"
    assert agent.ensure_summary(ok, _trace(rm)) == ok


def test_same_item_different_values_both_summarized_and_duplicates_merged():
    a = judge_checkup_item("총콜레스테롤", 210, "mg/dL")
    b = judge_checkup_item("총콜레스테롤", 250, "mg/dL")
    out = agent.ensure_summary("결과입니다.", _trace(a, b, a))
    summary = out.split("[판정 요약]")[1]
    assert _has_line(summary, "총콜레스테롤", "210") and _has_line(summary, "총콜레스테롤", "250")
    assert summary.count("210") == 1


def test_value_substring_is_not_a_match():
    r = judge_checkup_item("혈색소", 12, "g/dL", sex="남")
    ans = f"혈색소 (남 기준) 112 g/dL: {r['band']} (기준 {r['range']})"
    assert "[판정 요약]" in agent.ensure_summary(ans, _trace(r))


def test_model_line_with_only_loose_range_is_not_accepted():
    r = judge_checkup_item("공복혈당", 110, "mg/dL")
    ans = "공복혈당 110 mg/dL: 경계 (100 ~ 125, 공복 기준)"
    assert "[판정 요약]" in agent.ensure_summary(ans, _trace(r))


def test_generated_lines_match_trait_code_patterns():
    from evaluation.run_eval import TRAIT_CODE_PATTERNS
    g = judge_checkup_item("공복혈당", 110, "mg/dL")
    out = agent.ensure_summary("결과입니다.", _trace(g))
    assert TRAIT_CODE_PATTERNS["기준 범위(100 이상 126 미만) 표기"].search(out)
    b = calc_bmi(170, 79.2)
    r = judge_checkup_item("체질량지수", b["bmi"])
    assert TRAIT_CODE_PATTERNS["체질량지수 27.4 표기"].search(agent.ensure_summary("비만", _trace(r, bmi=b)))


def test_disclaimer_stays_last_line():
    r = judge_checkup_item("공복혈당", 110, "mg/dL")
    ans = agent.ensure_summary(agent.ensure_band_consistency("경계입니다.", _trace(r)), _trace(r))
    final = agent._result(ans, [], _trace(r))["answer"]
    assert final.split("\n")[-1] == agent.DISCLAIMER and "[판정 요약]" in final
