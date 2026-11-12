"""judge 호출 방식을 가짜 모델로 확인한다. 실제 Bedrock 호출 없음."""
import pytest

from evaluation import llm_judge
from src import agent


class _Throttle(Exception):
    """Bedrock ThrottlingException 흉내."""
    def __init__(self):
        super().__init__("ThrottlingException: Too many tokens")
        self.response = {"Error": {"Code": "ThrottlingException"}}


class _Reply:
    def __init__(self, text):
        self.content = text


def _factory(calls, behavior):
    class _M:
        def __init__(self, tier):
            self.tier = tier

        def invoke(self, prompt):
            calls.append((self.tier, prompt))
            return behavior(self.tier)
    return lambda region, model_id: _M((region, model_id))


OK = '{"forbidden": [{"id": "F1", "violated": false}], "traits": [{"id": "T1", "met": true}]}'


def test_프롬프트에는_질문_answer_체크리스트만_있고_reference는_없다():
    p = llm_judge.build_prompt("질문입니다", "답변입니다", ["당뇨병 단정"], ["안내가 있는가"])
    assert all(s in p for s in ("질문입니다", "답변입니다", "당뇨병 단정", "안내가 있는가"))
    with pytest.raises(TypeError):
        llm_judge.build_prompt("q", "a", [], [], reference="정답")


def test_1차_정상이면_1번만_호출하고_결과를_해석한다():
    calls = []
    out = llm_judge.judge("q", "a", ["f"], ["t"], _factory(calls, lambda t: _Reply(OK)))
    assert len(calls) == 1 and calls[0][0] == agent.MODEL_ORDER[0]
    assert out["verdicts"]["traits"][0]["met"] is True
    assert out["raw"] == OK and out["model"]["model_id"] == agent.MODEL_ORDER[0][1]


def test_MODEL_ORDER와_temperature_0으로_모델을_만든다(monkeypatch):
    seen = {}

    class _Fake:
        def __init__(self, **kw):
            seen.update(kw)

        def invoke(self, prompt):
            return _Reply(OK)

    import langchain_aws
    monkeypatch.setattr(langchain_aws, "ChatBedrockConverse", _Fake)
    llm_judge.judge("q", "a", [], [])
    region, model_id = agent.MODEL_ORDER[0]
    assert seen == {"model": model_id, "region_name": region, "temperature": 0}


def test_한도면_다음_차수로_넘어간다():
    calls = []

    def behavior(tier):
        if tier in agent.MODEL_ORDER[:3]:
            raise _Throttle()
        return _Reply(OK)

    out = llm_judge.judge("q", "a", [], [], _factory(calls, behavior))
    assert [c[0] for c in calls] == agent.MODEL_ORDER[:4]
    assert out["model"]["model_id"] == agent.MODEL_ORDER[3][1]


def test_한도가_아닌_예외는_넘기지_않고_올린다():
    calls = []

    def behavior(tier):
        raise ValueError("ValidationException")

    with pytest.raises(ValueError):
        llm_judge.judge("q", "a", [], [], _factory(calls, behavior))
    assert len(calls) == 1


def test_10개가_다_막히면_한도_예외를_올린다():
    calls = []

    def behavior(tier):
        raise _Throttle()

    with pytest.raises(_Throttle):
        llm_judge.judge("q", "a", [], [], _factory(calls, behavior))
    assert len(calls) == len(agent.MODEL_ORDER)


def test_해석_불가_원문은_verdicts_None():
    out = llm_judge.judge("q", "a", [], [], _factory([], lambda t: _Reply("모르겠음")))
    assert out["verdicts"] is None and out["raw"] == "모르겠음"
