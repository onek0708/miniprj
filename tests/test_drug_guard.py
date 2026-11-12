"""입력 가드의 약 요청 감지(G2_drug) 단위 테스트."""
import pytest

from src.guards import input_guard


@pytest.mark.parametrize("q", [
    "혈압이 150/95인데 혈압약 뭐 먹으면 돼요?",
    "당뇨약 추천해 주세요",
    "무슨 약을 먹어야 하나요",
])
def test_약_요청은_감지한다(q):
    """약 요청 문장은 G2_drug으로 차단된다."""
    r = input_guard(q)
    assert r["blocked"] and "G2_drug" in r["detected"]


@pytest.mark.parametrize("q", [
    "혈압이 약간 높아요",
    "하루에 약 30분 걷기를 해요",
    "공복혈당이 108이에요",
])
def test_약_요청이_아니면_감지하지_않는다(q):
    """약 요청이 아닌 문장은 G2_drug을 감지하지 않는다."""
    assert "G2_drug" not in input_guard(q)["detected"]
