"""필수 패턴 1(구조화 출력)·3(RAG)·11(트레이스)·12(평가) 구현 확인."""
import csv
from pathlib import Path

from src import agent
from src.retriever import hybrid_search, keyword_search, load_chunks
from src.agent import BmiOutput, JudgeOutput
from src.tools import calc_bmi, judge_checkup_item

ROOT = Path(__file__).resolve().parent.parent


def test_pattern1_tool_results_fit_pydantic_schemas():
    r = JudgeOutput(**judge_checkup_item("공복혈당", 125.9))
    assert r.status == "판정" and r.band == "경계"
    assert JudgeOutput(**judge_checkup_item("공복혈당", 126)).band == "질환의심"
    assert JudgeOutput(**judge_checkup_item("수축기 혈압", 900)).status == "보류"
    assert JudgeOutput(**judge_checkup_item("허리둘레", 88)).model_extra["by_sex"]
    assert BmiOutput(**calc_bmi(172, 81)).bmi == 27.4


def test_pattern3_chunks_and_hybrid_search_without_vector():
    chunks = load_chunks()
    assert chunks and all(c["doc_id"].startswith("guides/") and "#" in c["doc_id"] for c in chunks)
    assert keyword_search("콜레스테롤 식습관")
    found, status = hybrid_search("콜레스테롤 식습관")  # 벡터 모듈이 없어도 키워드로 계속
    assert found and status["keyword"] == "ok"


def test_pattern11_trace_is_step_list(monkeypatch):
    monkeypatch.setattr(agent, "_invoke_agent", lambda q: {
        "answer": "x", "contexts": [{"doc_id": "guides/a.md#b", "text": "t"}],
        "trace": [{"step": "judge_checkup_item", "input": "{}", "output": "{}"}]})
    out = agent.run_query("공복혈당 108")
    assert [s["step"] for s in out["trace"]] == ["input_guard", "judge_checkup_item"]


def test_pattern12_eval_set_tools_match_trace_step_names():
    rows = list(csv.DictReader(open(ROOT / "evaluation" / "test_queries.csv", encoding="utf-8")))
    names = {t for r in rows for t in r["expected_tools"].split(";") if t}
    assert names <= {"judge_checkup_item", "calc_bmi", "retrieve_guides"}
    assert len(rows) == 20
