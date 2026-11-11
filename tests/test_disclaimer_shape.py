"""면책 문장과 세 키 응답 형식, 실패 시 서버 유지 테스트."""
import pytest
from fastapi.testclient import TestClient

import src.agent as agent
from src.agent import DISCLAIMER, run_query
from src.app import app

client = TestClient(app)


def _check(data):
    assert set(data) == {"answer", "contexts", "trace"}
    assert data["answer"].endswith(DISCLAIMER)
    assert data["answer"].count(DISCLAIMER) == 1


@pytest.mark.parametrize("q", [None, "", "  ", 5, ["a"], "가" * 501, "혈압약 추천해 줘"])
def test_run_query_shape(q):
    _check(run_query(q))


def test_bedrock_failure_keeps_shape(monkeypatch):
    def boom(q):
        raise RuntimeError("bedrock down")
    monkeypatch.setattr(agent, "_invoke_agent", boom)
    data = run_query("공복혈당 110이면?")
    _check(data)
    assert data["trace"][-1]["step"] == "error"
    _check(client.post("/query", json={"question": "공복혈당 110이면?"}).json())


def test_retrieval_failure_tool_says_no_guide(monkeypatch):
    pytest.importorskip("langchain_core")
    def boom(q):
        raise RuntimeError("chroma down")
    monkeypatch.setattr(agent, "retrieve_guides", boom)
    rec = agent._Recorder()
    tool = agent._build_tools(rec)[2]
    assert tool.invoke({"query": "혈압 지침"}) == "근거 지침 없음"
    assert rec.contexts == []
    assert "실패" in rec.trace[0]["output"]
