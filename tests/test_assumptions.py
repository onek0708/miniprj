"""가정과 환산 명시: mmol/L 환산값, 공복 가정, 성별 미입력 시 남녀 기준을 답에 밝힌다."""
import json

from src import agent
from src.tools import judge_checkup_item


def _trace(*results):
    return [{"step": "judge_checkup_item", "input": "{}", "output": json.dumps(r, ensure_ascii=False)}
            for r in results]


def test_mmol_conversion_and_fasting_assumption_appended():
    trace = _trace(judge_checkup_item("공복혈당", 7.0, "mmol/L", "남"))
    out = agent.ensure_assumptions("공복혈당은 질환의심입니다.", trace)
    assert "환산" in out and "126 mg/dL" in out and "공복 가정" in out


def test_cholesterol_and_triglyceride_conversion_stated():
    trace = _trace(judge_checkup_item("총콜레스테롤", 5.0, "mmol/L"),
                   judge_checkup_item("중성지방", 1.7, "mmol/L"))
    out = agent.ensure_assumptions("판정했습니다.", trace)
    assert out.count("mmol/L → mg/dL 환산") == 2


def test_missing_sex_states_both_standards():
    r = judge_checkup_item("혈색소", 12.5)
    assert r["by_sex"]["남"]["band"] != r["by_sex"]["여"]["band"]
    out = agent.ensure_assumptions("혈색소 판정입니다.", _trace(r))
    assert "성별 미입력: 남녀 기준 모두 제시" in out


def test_no_duplicate_when_answer_already_states():
    trace = _trace(judge_checkup_item("공복혈당", 7.0, "mmol/L", "남"))
    answer = "7.0 mmol/L은 126 mg/dL로 환산했고 공복 상태로 가정했습니다."
    assert agent.ensure_assumptions(answer, trace) == answer


def test_no_assumption_nothing_added():
    trace = _trace(judge_checkup_item("공복혈당", 110, "mg/dL", None, True))
    assert agent.ensure_assumptions("경계입니다.", trace) == "경계입니다."


def test_run_query_includes_assumptions(monkeypatch):
    trace = _trace(judge_checkup_item("공복혈당", 7.0, "mmol/L"))
    monkeypatch.setattr(agent, "_invoke_agent", lambda q: {
        "answer": agent.ensure_assumptions("질환의심입니다.", trace), "contexts": [], "trace": trace})
    out = agent.run_query("혈당 7.0 mmol/L")
    assert "환산" in out["answer"] and "공복 가정" in out["answer"]
