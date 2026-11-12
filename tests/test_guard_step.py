"""_guard_step의 trace 감지 문구 단위 테스트 (Bedrock 호출 없음)."""
from src.agent import _guard_step


def test_통과이고_감지없음이면_없음이라고_쓴다():
    """감지가 없으면 '감지: 없음'만 쓴다."""
    step = _guard_step("q", {"blocked": False, "detected": []})
    assert step["output"] == "통과 (감지: 없음)"


def test_통과여도_실제_감지항목을_쓴다():
    """차단이 아니어도 G4·G5 감지 항목을 문장에 쓴다."""
    step = _guard_step("q", {"blocked": False, "detected": ["G4_pii", "G5_injection"]})
    assert step["output"] == "통과 (감지: G4_pii, G5_injection)"
    assert step["detected"] == ["G4_pii", "G5_injection"] and step["blocked"] is False


def test_차단이면_기존_문구를_유지한다():
    """차단 문구와 필드·단계 구조는 그대로다."""
    step = _guard_step("q", {"blocked": True, "detected": ["G2_drug"]})
    assert step["output"] == "차단 (감지: G2_drug)"
    assert set(step) == {"step", "input", "output", "detected", "blocked"}
    assert step["step"] == "input_guard"
