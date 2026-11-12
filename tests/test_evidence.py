"""근거 표기: 판정 기준 출처, 지침 contexts·출처, 검색 0건이면 '근거 지침 없음'."""
import json

from src import agent
from src.tools import judge_checkup_item


def _trace(*results):
    return [{"step": "judge_checkup_item", "input": "{}", "output": json.dumps(r, ensure_ascii=False)}
            for r in results]


def test_source_and_base_date_appended_for_judgment():
    r = judge_checkup_item("공복혈당", 90, "mg/dL", "남", True)
    out, ctx = agent.ensure_evidence("정상입니다.", "공복혈당 90", [], _trace(r))
    assert r["source"] in out and r["base_date"] in out
    assert ctx == []  # 정상 판정만이면 지침 검색을 강제하지 않는다


def test_borderline_without_model_retrieval_fills_contexts_with_sources():
    r = judge_checkup_item("공복혈당", 110, "mg/dL", "남", True)
    out, ctx = agent.ensure_evidence("경계입니다.", "공복혈당 110", [], _trace(r))
    assert ctx and "[지침 출처]" in out and "질병관리청" in out


def test_suspect_by_sex_counts_as_flagged():
    r = judge_checkup_item("혈색소", 11.0)
    out, ctx = agent.ensure_evidence("판정.", "혈색소 11", [], _trace(r))
    assert ctx


def test_guide_question_without_judgment_gets_contexts():
    out, ctx = agent.ensure_evidence("답.", "혈압 낮추는 생활습관 지침 알려줘", [], [])
    assert ctx and "[지침 출처]" in out


def test_zero_results_states_no_guide_and_invents_nothing(monkeypatch):
    monkeypatch.setattr(agent, "retrieve_guides", lambda q: ([], {}))
    r = judge_checkup_item("공복혈당", 130, "mg/dL", "남", True)
    out, ctx = agent.ensure_evidence("질환의심입니다.", "공복혈당 130", [], _trace(r))
    assert ctx == [] and "근거 지침 없음" in out and "[지침 출처]" not in out
    assert r["source"] in out


def test_retrieval_exception_states_no_guide(monkeypatch):
    def boom(q):
        raise RuntimeError("chroma down")
    monkeypatch.setattr(agent, "retrieve_guides", boom)
    out, ctx = agent.ensure_evidence("답.", "식습관 지침", [], [])
    assert ctx == [] and "근거 지침 없음" in out


def test_no_duplicate_when_already_cited():
    r = judge_checkup_item("공복혈당", 110, "mg/dL", "남", True)
    ctxs = [{"doc_id": "guides/blood_sugar.md#혈당 - 식습관", "text": "t"}]
    ans = f"{r['source']} {r['base_date']} guides/blood_sugar.md#혈당 - 식습관"
    out, _ = agent.ensure_evidence(ans, "공복혈당 110", ctxs, _trace(r))
    assert out == ans


def test_unsupported_exam_drops_unrelated_guides_and_skips_search(monkeypatch):
    called = []
    monkeypatch.setattr(agent, "retrieve_guides", lambda q: called.append(q) or ([], {}))
    ctxs = [{"doc_id": "guides/blood_pressure.md#혈압 - 재검사", "text": "t"}]
    out, ctx = agent.ensure_evidence("다루지 않는 검사입니다.", "위암 검진 결과가 이상 소견이래요 어떻게 해석해요", ctxs, [])
    assert ctx == [] and called == [] and out == "다루지 않는 검사입니다."


def test_only_guides_matching_judged_items_are_kept():
    r = judge_checkup_item("공복혈당", 110, "mg/dL", "남", True)
    ctxs = [{"doc_id": "guides/blood_sugar.md#혈당 - 식습관", "text": "t"},
            {"doc_id": "guides/blood_pressure.md#혈압 - 재검사", "text": "t"}]
    _, ctx = agent.ensure_evidence("경계입니다.", "공복혈당 110", ctxs, _trace(r))
    assert [c["doc_id"] for c in ctx] == ["guides/blood_sugar.md#혈당 - 식습관"]


def test_hold_only_has_no_source_note():
    r = judge_checkup_item("공복혈당", 9999, "mg/dL", "남", True)
    out, ctx = agent.ensure_evidence("보류.", "공복혈당 9999", [], _trace(r))
    assert out == "보류." and ctx == []
