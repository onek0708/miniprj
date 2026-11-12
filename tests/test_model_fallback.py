"""주 모델 한도(ThrottlingException) 시 예비 모델로 질문을 다시 처리하는지 가짜 모델로 확인한다."""
import pytest

from src import agent


class _Throttle(Exception):
    """Bedrock ThrottlingException 흉내."""
    def __init__(self):
        super().__init__("ThrottlingException: Too many tokens")
        self.response = {"Error": {"Code": "ThrottlingException"}}


def _fake_run(calls, fail_on):
    def run(question, model_id):
        calls.append(model_id)
        if model_id in fail_on:
            raise _Throttle()
        return {"answer": "답", "contexts": [], "trace": []}
    return run


def test_모델_설정():
    assert agent.PRIMARY_MODEL == "us.anthropic.claude-sonnet-4-6"
    assert agent.FALLBACK_MODEL == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert agent.MODEL_REGION == "us-west-2"


def test_주_모델_정상이면_예비_모델_안_씀(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_run_agent", _fake_run(calls, set()))
    out = agent._invoke_agent("질문")
    assert calls == [agent.PRIMARY_MODEL]
    assert out["trace"][-1] == {"step": "llm_model", "input": "us-west-2", "output": agent.PRIMARY_MODEL}


def test_한도면_예비_모델로_다시_처리(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_run_agent", _fake_run(calls, {agent.PRIMARY_MODEL}))
    out = agent._invoke_agent("질문")
    assert calls == [agent.PRIMARY_MODEL, agent.FALLBACK_MODEL]
    assert out["trace"][-1]["output"] == agent.FALLBACK_MODEL
    assert set(out) == {"answer", "contexts", "trace"}


def test_한도가_아닌_오류는_그대로_던짐(monkeypatch):
    def run(question, model_id):
        raise ValueError("다른 오류")
    monkeypatch.setattr(agent, "_run_agent", run)
    with pytest.raises(ValueError):
        agent._invoke_agent("질문")


def test_두_모델_모두_한도면_예외(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_run_agent", _fake_run(calls, {agent.PRIMARY_MODEL, agent.FALLBACK_MODEL}))
    with pytest.raises(_Throttle):
        agent._invoke_agent("질문")
    assert calls == [agent.PRIMARY_MODEL, agent.FALLBACK_MODEL]
