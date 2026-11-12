"""evaluation/llm_judge.py 단위 테스트: 실제 Bedrock 호출 없이 가짜 모델로 확인한다."""
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evaluation"))

import llm_judge  # noqa: E402
from src.agent import MODEL_ORDER  # noqa: E402

CRIT = ["단정하지 않는다", "안내를 포함한다"]
OK_JSON = json.dumps({"results": [{"criterion": c, "verdict": "충족", "reason": "근거"} for c in CRIT]}, ensure_ascii=False)


class Throttle(Exception):
    """한도 예외 흉내."""
    response = {"Error": {"Code": "ThrottlingException"}}


class Msg:
    """모델 응답 흉내."""

    def __init__(self, content):
        self.content = content


def factory(behaviors, calls):
    """호출마다 behaviors를 하나씩 소비하는 가짜 모델 공장."""
    def make(region, model_id):
        class M:
            def invoke(self, prompt):
                calls.append((region, model_id, prompt))
                b = behaviors.pop(0)
                if isinstance(b, Exception):
                    raise b
                return Msg(b)
        return M()
    return make


@pytest.fixture(autouse=True)
def _reset():
    llm_judge._THROTTLED_TIERS.clear()


def test_한_번_호출에_기준_전부_판정():
    calls = []
    r = llm_judge.judge_answer("질문", "답", CRIT, factory([OK_JSON], calls))
    assert len(calls) == 1 and r["status"] == "판정"
    assert [v["criterion"] for v in r["verdicts"]] == CRIT
    assert all(c in calls[0][2] for c in CRIT)


def test_위반_해석():
    bad = json.dumps({"results": [{"verdict": "위반", "reason": "단정"}, {"verdict": "충족", "reason": "ok"}]}, ensure_ascii=False)
    r = llm_judge.judge_answer("q", "a", CRIT, factory([bad], []))
    assert [v["verdict"] for v in r["verdicts"]] == ["위반", "충족"] and r["verdicts"][0]["reason"] == "단정"


def test_한도시_다음_차수로_처음부터():
    calls = []
    r = llm_judge.judge_answer("q", "a", CRIT, factory([Throttle(), OK_JSON], calls))
    assert [c[:2] for c in calls] == list(MODEL_ORDER[:2]) and calls[0][2] == calls[1][2]
    assert r["model"] == MODEL_ORDER[1][1] and r["region"] == MODEL_ORDER[1][0]


def test_모든_차수_한도면_멈춤():
    with pytest.raises(llm_judge.AllTiersThrottled):
        llm_judge.judge_answer("q", "a", CRIT, factory([Throttle()] * 10, []))


def test_해석불가는_재시도_후_판정불가():
    calls = []
    r = llm_judge.judge_answer("q", "a", CRIT, factory(["이상한 글", "{}"], calls))
    assert len(calls) == 2 and r["status"] == "판정불가" and r["verdicts"] == []


def test_호출실패는_재시도_후_성공하거나_판정불가():
    calls = []
    r = llm_judge.judge_answer("q", "a", CRIT, factory([ValueError("boom"), OK_JSON], calls))
    assert r["status"] == "판정" and len(calls) == 2
    r2 = llm_judge.judge_answer("q", "a", CRIT, factory([ValueError("x"), ValueError("y")], []))
    assert r2["status"] == "판정불가" and "호출 실패" in r2["error"]


def test_temperature_0():
    assert "temperature=0" in inspect.getsource(llm_judge.make_model)
