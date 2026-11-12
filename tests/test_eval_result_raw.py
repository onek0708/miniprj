"""평가 결과에 trace 전체와 judge 원문이 문항별로 저장되는지 확인한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))
import run_eval  # noqa: E402


def test_result_keeps_trace_and_judge_raw(monkeypatch):
    """judge가 통과시킨 문항에도 trace와 judge_raw가 남는다."""
    trace = [{"step": "llm_model", "input": "r", "output": "m"}]
    monkeypatch.setattr(run_eval, "run_query", lambda q: {"answer": "답 " + run_eval.DISCLAIMER, "contexts": [], "trace": trace})
    row = {"id": "1", "category": "x", "input": "q", "expected_traits": "가나", "forbidden": "다라",
           "expected_tools": ""}

    def fake(q, a, forb, trt):
        return {"raw": "원문", "verdicts": {"forbidden": [{"id": "F1", "violated": False}],
                                           "traits": [{"id": "T1", "met": True}]}}

    res = run_eval.evaluate_row(row, judge_fn=fake)
    assert res["trace"] == trace
    assert res["judge_raw"] == "원문"
