"""검색 설정 비교 옵션 테스트: 저장된 질문문으로 검색만 다시 실행하고 검색 지표 둘만 잰다 (실제 Bedrock 호출 없음)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_ragas  # noqa: E402

ROWS = [{"id": "1", "input": "q1", "reference": "r1"}, {"id": "2", "input": "q2", "reference": "r2"},
        {"id": "3", "input": "q3", "reference": "r3"}]


def _queries(tmp_path):
    p = tmp_path / "q.json"
    p.write_text(json.dumps({"queries": {"1": ["a", "b"], "2": ["c"]}}), encoding="utf-8")
    return p


def test_검색_인자와_중복_제거_제외_문항(tmp_path, capsys):
    calls = []

    def fake(q, k, kw, vw):
        calls.append((q, k, kw, vw))
        return [{"doc_id": "d1", "text": "t1"}, {"doc_id": "d2" if q == "a" else "d1", "text": "t2"}], {}

    samples, excluded = run_ragas.build_retrieval_samples(ROWS, _queries(tmp_path), 5, 0.7, 0.3, fake)
    assert calls[0] == ("a", 5, 0.7, 0.3)
    assert excluded == ["3"]
    assert samples[0]["doc_ids"] == ["d1", "d2"]
    out = capsys.readouterr().out
    assert "#1" in out and "채점 모델" in out


def test_두_지표만_재고_NaN이면_무효(tmp_path):
    seen = []

    def scorer(samples, model, region):
        seen.append(model)
        return [{"context_recall": 1.0, "llm_context_precision_with_reference": 0.5},
                {"context_recall": float("nan"), "llm_context_precision_with_reference": 0.5}]

    fake = lambda q, k, kw, vw: ([{"doc_id": "d", "text": "t"}], {})  # noqa: E731
    r = run_ragas.run_retrieval_round(ROWS, _queries(tmp_path), 3, 1.0, 1.0, scorer, fake)
    assert set(r["metrics"]) == {"context_recall", "context_precision"}
    assert r["valid"] is False and r["nan_ids"] == ["2"]
    assert r["judge_model"].startswith(run_ragas.JUDGE_MODEL)


def test_한도로_넘어간_차수의_모델과_리전이_결과에_기록됨(tmp_path):
    from src.agent import MODEL_ORDER

    class ThrottlingException(Exception):
        pass

    calls = []

    def scorer(samples, model, region):
        calls.append((region, model))
        if len(calls) == 1:
            raise ThrottlingException("limit")
        return [{"context_recall": 1.0, "llm_context_precision_with_reference": 1.0}] * len(samples)

    fake = lambda q, k, kw, vw: ([{"doc_id": "d", "text": "t"}], {})  # noqa: E731
    r = run_ragas.run_retrieval_round(ROWS, _queries(tmp_path), 3, 1.0, 1.0, scorer, fake)
    region, model = MODEL_ORDER[1]
    assert calls == MODEL_ORDER[:2]
    assert r["judge_model"] == f"{model} ({region})"
