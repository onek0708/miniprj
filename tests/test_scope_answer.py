"""범위 밖·수치 없는 질문: 도구 호출이 없으면 코드가 고정 문장으로 답한다 (가짜 모델)."""
import json

from src import agent

_ITEMS = ["수축기 혈압", "이완기 혈압", "공복혈당", "총콜레스테롤", "중성지방", "HDL 콜레스테롤",
          "LDL 콜레스테롤", "체질량지수", "허리둘레", "AST", "ALT", "감마지티피", "혈색소"]


def test_고정문장_필수_내용():
    t = agent.FIXED_ANSWER
    assert all(i in t for i in _ITEMS)
    assert "다루지 않는 검사" in t and "영상" in t and "암" in t
    assert "수치" in t and "입력" in t
    assert "검진 기관" in t and "검진을 받은 병원" in t and "상담" in t
    assert not any(w in t for w in ("정상", "경계", "질환의심", "질환 의심"))


def test_도구_호출이_없으면_고정문장으로_바꾸고_trace에_남긴다():
    trace = []
    out, fixed = agent.ensure_scope_answer("CT 정상 범위는 ...", trace)
    assert fixed and out == agent.FIXED_ANSWER
    assert trace[-1]["step"] == "fixed_answer"


def test_도구_호출이_있으면_그대로_둔다():
    for name in ("judge_checkup_item", "calc_bmi", "retrieve_guides"):
        trace = [{"step": name, "input": "{}", "output": "{}"}]
        assert agent.ensure_scope_answer("모델 답", trace) == ("모델 답", False)
        assert len(trace) == 1


def test_run_agent는_모델이_도구를_안_쓰면_고정문장(monkeypatch):
    import langchain.agents
    import langchain_aws

    class _Msg:
        text = "흉부 CT는 정상 범위가 ..."

    class _Agent:
        def invoke(self, _):
            return {"messages": [_Msg()]}

    monkeypatch.setattr(langchain_aws, "ChatBedrockConverse", lambda **k: object())
    monkeypatch.setattr(langchain.agents, "create_agent", lambda *a, **k: _Agent())
    out = agent._run_agent("흉부 CT 결과 알려줘", "m", "r")
    assert out["answer"] == agent.FIXED_ANSWER and out["contexts"] == []
    assert [s["step"] for s in out["trace"]] == ["fixed_answer"]
    json.dumps(out)
