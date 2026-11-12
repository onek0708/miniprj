"""판정할 수 없는 질문의 고정 문장과 적용 조건의 경계 (실제 Bedrock 호출 없음)."""
import json

from src import agent
from src.tools import calc_bmi, judge_checkup_item

BAND_WORDS = ("정상", "경계", "질환의심")


def _trace(*results, bmi=None):
    t = [{"step": "judge_checkup_item", "input": "{}", "output": json.dumps(r, ensure_ascii=False)} for r in results]
    if bmi:
        t.append({"step": "calc_bmi", "input": "{}", "output": json.dumps(bmi, ensure_ascii=False)})
    return t


def test_no_result_no_guide_uses_fixed_message():
    out = agent.ensure_unjudgeable("모델이 지어낸 긴 일반 지식", [], [])
    assert out == agent.UNJUDGEABLE_MESSAGE
    assert "검진 기관" in out and "120/80" in out and "설명드릴 수 없" in out
    assert not any(w in out for w in BAND_WORDS)


def test_hold_only_without_guide_writes_tool_reason_and_consult():
    r = judge_checkup_item("갑상선자극호르몬", 3.0, "mIU/L")
    assert r["status"] == "보류"
    out = agent.ensure_unjudgeable("정상 범위는 0.4~4.0입니다.", [], _trace(r))
    assert r["reason"] in out and "검진 기관" in out
    assert "0.4~4.0" not in out


def test_partial_judged_keeps_model_answer():
    ok = judge_checkup_item("공복혈당", 110, "mg/dL")
    hold = judge_checkup_item("갑상선자극호르몬", 3.0, "mIU/L")
    assert agent.ensure_unjudgeable("모델 답", [], _trace(ok, hold)) == "모델 답"


def test_guide_present_keeps_model_answer():
    assert agent.ensure_unjudgeable("모델 답", [{"doc_id": "a#1", "text": "t"}], []) == "모델 답"


def test_bmi_result_keeps_model_answer():
    assert agent.ensure_unjudgeable("모델 답", [], _trace(bmi=calc_bmi(170, 70))) == "모델 답"


def test_run_query_applies_fixed_message_and_disclaimer_last(monkeypatch):
    monkeypatch.setattr(agent, "_invoke_agent", lambda q: {"answer": "지어낸 답", "contexts": [], "trace": []})
    res = agent.run_query("오늘 점심 뭐 먹지")
    assert res["answer"].startswith(agent.UNJUDGEABLE_MESSAGE)
    assert res["answer"].endswith(agent.DISCLAIMER)
    assert set(res) == {"answer", "contexts", "trace"}
