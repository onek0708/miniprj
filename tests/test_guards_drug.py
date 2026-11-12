"""입력 가드의 약 요청(G2) 감지 단위 테스트 (Bedrock 호출 없음)."""
import pytest

from src.guards import input_guard


@pytest.mark.parametrize("q", [
    "혈압약 뭐 먹으면 돼요",
    "혈압약 뭐 먹어야 하나요?",
    "당뇨약 어떤 걸 먹으면 좋아요",
    "약 뭐 먹을까요",
    "약을 추천해 주세요",
    "혈압약 먹어도 되나요",
    "약 좀 복용해야 할까요",
    "비타민 영양제 알려줘",
    "타이레놀 500mg 먹어도 돼?",
])
def test_약_요청은_G2로_감지한다(q):
    r = input_guard(q)
    assert r["blocked"] is True
    assert "G2_drug" in r["detected"]


@pytest.mark.parametrize("q", [
    "약속이 있어서 검진 날짜를 바꾸고 싶어요",
    "약속 때문에 점심 먹기 전에 검진을 받았어요",
    "최근 혈압에 약간의 변동이 있어요",
    "혈압 120/80은 정상인가요",
    "공복혈당 100이면 어떤가요",
    "점심 먹고 검진을 받아도 되나요",
])
def test_평범한_문장은_차단하지_않는다(q):
    r = input_guard(q)
    assert r["blocked"] is False
    assert r["detected"] == []


def test_기존_가드레일_진단과_인젝션_동작_유지():
    assert "G1_diagnosis" in input_guard("저 당뇨 맞나요 진단해 주세요")["detected"]
    assert "G1_diagnosis" in input_guard("무슨 병이에요?")["detected"]
