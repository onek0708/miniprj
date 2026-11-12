"""지원하지 않는 검사 항목 보류: 코드가 범위 밖 안내와 검진 기관 상담 권유를 덧붙인다 (가짜 trace)."""
import json

from src import agent


def _step(item, reason, status="보류"):
    out = {"status": status, "item": item, "band": None, "reason": reason, "assumptions": []}
    return {"step": "judge_checkup_item", "input": "{}", "output": json.dumps(out, ensure_ascii=False)}


def test_지원하지_않는_항목이면_안내와_상담_권유를_덧붙인다():
    trace = [_step("갑상선자극호르몬", agent.UNSUPPORTED_REASON)]
    out = agent.ensure_unsupported_notice("모델 설명입니다.", trace)
    assert out.startswith("모델 설명입니다.")  # 모델 문장은 지우지 않는다
    assert "갑상선자극호르몬" in out and "다루지 않는 검사" in out
    assert "검진 기관" in out and "상담" in out


def test_이미_안내가_있으면_중복하지_않는다():
    trace = [_step("갑상선자극호르몬", agent.UNSUPPORTED_REASON)]
    answer = "갑상선자극호르몬은 다루지 않는 검사입니다. 검진 기관에 상담하세요."
    assert agent.ensure_unsupported_notice(answer, trace) == answer


def test_다른_사유_보류나_판정은_건드리지_않는다():
    trace = [_step("공복혈당", "입력값이 허용 범위를 벗어났습니다."), _step("혈색소", "", "판정")]
    assert agent.ensure_unsupported_notice("답", trace) == "답"


def test_여러_항목은_모두_나열한다():
    trace = [_step("CEA", agent.UNSUPPORTED_REASON), _step("PSA", agent.UNSUPPORTED_REASON)]
    out = agent.ensure_unsupported_notice("답", trace)
    assert "CEA" in out and "PSA" in out


def test_시스템_프롬프트에_지어내지_말라는_지시():
    p = agent.SYSTEM_PROMPT
    assert "지원하지 않는" in p and "참고 범위" in p and "질환 가능성" in p and "검사 설명" in p and "지어내지" in p
