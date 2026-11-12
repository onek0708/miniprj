"""공복 가정 보장: 사용자가 금식·공복 상태를 말하지 않았으면 코드가 '공복 가정' 문장을 덧붙인다."""
import json

from src import agent
from src.tools import judge_checkup_item

PII_Q = "제 주민등록번호는 900101-1234567이고 공복혈당은 92예요"


def _trace(fasting):
    r = judge_checkup_item("공복혈당", 92, "mg/dL", None, fasting)
    return [{"step": "judge_checkup_item", "input": "{}", "output": json.dumps(r, ensure_ascii=False)}]


def test_pii_question_with_fasting_true_gets_assumption():
    out = agent.ensure_fasting_assumption("공복혈당 92는 정상입니다.", PII_Q, _trace(True))
    assert agent.FASTING_ASSUMPTION in out


def test_fasting_none_not_duplicated_after_ensure_assumptions():
    trace = _trace(None)
    out = agent.ensure_assumptions("공복혈당 92는 정상입니다.", trace)
    out = agent.ensure_fasting_assumption(out, PII_Q, trace)
    assert out.count("공복 가정") == 1 and agent.FASTING_ASSUMPTION not in out


def test_user_stated_fasting_expressions():
    for q in ("8시간 금식 후 공복혈당 92", "공복 상태로 쟀는데 공복혈당 92", "아침 안 먹고 공복혈당 92"):
        assert agent.user_stated_fasting(q)
        assert agent.ensure_fasting_assumption("정상입니다.", q, _trace(True)) == "정상입니다."
    assert not agent.user_stated_fasting(PII_Q)


def test_answer_already_states_assumption_unchanged():
    ans = "공복 상태로 가정하고 판정했습니다."
    assert agent.ensure_fasting_assumption(ans, PII_Q, _trace(True)) == ans


def test_no_fasting_glucose_judgment_nothing_added():
    r = judge_checkup_item("총콜레스테롤", 180, "mg/dL")
    trace = [{"step": "judge_checkup_item", "input": "{}", "output": json.dumps(r, ensure_ascii=False)}]
    assert agent.ensure_fasting_assumption("정상", "총콜레스테롤 180", trace) == "정상"


def test_system_prompt_has_fasting_rule():
    assert "fasting을 비운다" in agent.SYSTEM_PROMPT
