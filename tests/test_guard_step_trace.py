"""trace의 input_guard 출력 문장이 실제 감지 항목을 보여주는지 확인한다."""
from src.agent import _guard_step


def test_통과이고_감지_없음():
    """감지가 없으면 '통과 (감지: 없음)'을 쓴다."""
    step = _guard_step("q", {"blocked": False, "detected": []})
    assert step["output"] == "통과 (감지: 없음)"


def test_통과이지만_감지_있음():
    """차단이 아니어도 감지 항목을 문장에 쓴다."""
    step = _guard_step("q", {"blocked": False, "detected": ["G4_pii", "G5_injection"]})
    assert step["output"] == "통과 (감지: G4_pii, G5_injection)"


def test_차단은_기존_형식_유지():
    """차단 문장은 그대로 유지된다."""
    step = _guard_step("q", {"blocked": True, "detected": ["G1_drug"]})
    assert step["output"] == "차단 (감지: G1_drug)"
