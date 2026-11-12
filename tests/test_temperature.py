"""서비스 모델 호출에 temperature=0이 적용되는지 가짜 모델로 확인한다. 실제 Bedrock 호출 없음."""
import pytest

from src import agent


def test_모델_생성_때_temperature_0을_넘긴다(monkeypatch):
    """MODEL_ORDER의 모든 차수에서 ChatBedrockConverse가 temperature=0으로 만들어진다."""
    created = []

    class _가짜모델:
        def __init__(self, **kwargs):
            created.append(kwargs)

    class _가짜에이전트:
        def invoke(self, _):
            raise RuntimeError("중단")

    import langchain_aws
    monkeypatch.setattr(langchain_aws, "ChatBedrockConverse", _가짜모델)
    import langchain.agents
    monkeypatch.setattr(langchain.agents, "create_agent", lambda *a, **k: _가짜에이전트())

    for region, model_id in agent.MODEL_ORDER:
        with pytest.raises(RuntimeError):
            agent._run_agent("질문", model_id, region)

    assert len(created) == len(agent.MODEL_ORDER) == 10
    assert all(c["temperature"] == 0 for c in created)
    assert [(c["region_name"], c["model"]) for c in created] == agent.MODEL_ORDER
