"""SYSTEM_PROMPT에 답 구조·이모지 금지 지시와 기존 지시가 들어 있는지 확인한다."""
from src.agent import SYSTEM_PROMPT


def test_answer_structure_and_no_emoji():
    """답 순서 4단계와 이모지 금지 지시가 있다."""
    p = SYSTEM_PROMPT
    assert "인식한 수치" in p and "항목별 판정" in p and "기준 범위" in p
    assert "생활습관 지침과 근거" in p and "4) 안내" in p
    assert p.index("인식한 수치") < p.index("항목별 판정") < p.index("생활습관 지침") < p.index("4) 안내")
    assert "이모지는 쓰지 않는다" in p


def test_existing_instructions_kept():
    """기존 지시가 그대로 남아 있다."""
    p = SYSTEM_PROMPT
    for s in ["도구 결과 그대로", "보류 항목에는 구간을 쓰지 않는다", "되묻지 말고",
              "지어내지 말고", "진단명을 단정하거나 약·용량을 말하지 않는다", "의료기관 진료를 안내한다"]:
        assert s in p
