"""10단계 모델 순서 전환(질문 단위)을 가짜 모델로 확인한다. 실제 Bedrock 호출 없음."""
import pytest

from src import agent

S46, S45 = "sonnet-4-6", "sonnet-4-5-20250929"


class _Throttle(Exception):
    """Bedrock ThrottlingException 흉내."""
    def __init__(self):
        super().__init__("ThrottlingException: Too many tokens")
        self.response = {"Error": {"Code": "ThrottlingException"}}


@pytest.fixture(autouse=True)
def _초기화():
    agent._THROTTLED_TIERS.clear()
    yield
    agent._THROTTLED_TIERS.clear()


def _fake_run(calls, blocked):
    def run(question, model_id, region):
        calls.append((region, model_id))
        if (region, model_id) in blocked:
            raise _Throttle()
        return {"answer": "답", "contexts": [], "trace": []}
    return run


def test_모델_순서는_Seed의_10단계와_같다():
    assert agent.MODEL_ORDER == [
        ("us-west-2", "us.anthropic.claude-sonnet-4-6"),
        ("us-west-2", "global.anthropic.claude-sonnet-4-6"),
        ("us-east-1", "us.anthropic.claude-sonnet-4-6"),
        ("us-east-1", "global.anthropic.claude-sonnet-4-6"),
        ("ap-northeast-2", "global.anthropic.claude-sonnet-4-6"),
        ("us-west-2", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
        ("us-west-2", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
        ("us-east-1", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
        ("us-east-1", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
        ("ap-northeast-2", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ]


def test_1차_정상이면_넘어가지_않음(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_run_agent", _fake_run(calls, set()))
    out = agent._invoke_agent("질문")
    region, model_id = agent.MODEL_ORDER[0]
    assert calls == [agent.MODEL_ORDER[0]]
    assert out["trace"][-1] == {"step": "llm_model", "input": region, "output": model_id}


def test_한도면_순서대로_다음_차수로_처음부터_다시_처리(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_run_agent", _fake_run(calls, set(agent.MODEL_ORDER[:6])))
    out = agent._invoke_agent("질문")
    assert calls == agent.MODEL_ORDER[:7]
    assert out["trace"][-1]["output"] == agent.MODEL_ORDER[6][1]
    assert out["trace"][-1]["input"] == agent.MODEL_ORDER[6][0]
    assert set(out) == {"answer", "contexts", "trace"}


def test_한도가_아닌_오류는_넘어가지_않음(monkeypatch):
    calls = []
    def run(question, model_id, region):
        calls.append((region, model_id))
        raise ValueError("다른 오류")
    monkeypatch.setattr(agent, "_run_agent", run)
    with pytest.raises(ValueError):
        agent._invoke_agent("질문")
    assert calls == [agent.MODEL_ORDER[0]]


def test_막힌_차수는_다음_질문에서_건너뜀(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_run_agent", _fake_run(calls, {agent.MODEL_ORDER[0]}))
    agent._invoke_agent("질문1")
    calls.clear()
    out = agent._invoke_agent("질문2")
    assert calls == [agent.MODEL_ORDER[1]]
    assert out["trace"][-1]["output"] == agent.MODEL_ORDER[1][1]


def test_10개가_모두_막히면_예외(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_run_agent", _fake_run(calls, set(agent.MODEL_ORDER)))
    with pytest.raises(_Throttle):
        agent._invoke_agent("질문")
    assert calls == agent.MODEL_ORDER
    calls.clear()
    with pytest.raises(Exception):  # 이미 모두 막힌 상태에서는 Bedrock을 다시 부르지 않는다
        agent._invoke_agent("질문")
    assert calls == []


def test_Haiku_Nova_gpt_oss는_목록에_없음():
    text = " ".join(m for _, m in agent.MODEL_ORDER).lower()
    assert not any(x in text for x in ("haiku", "nova", "gpt-oss"))
