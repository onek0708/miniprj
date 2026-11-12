"""RAGAS 평가 스크립트: test_queries.csv 20건을 run_query로 돌려 RAGAS 4개 지표를 측정하고 JSON으로 저장한다.

사용법: python evaluation/run_ragas.py [--out 경로]
- 지표: context_recall, context_precision, faithfulness, answer_relevancy (측정만, 통과 기준 없음)
- 심판 모델: src/agent.py의 MODEL_ORDER 10단계(Sonnet 4.6 5개 → Sonnet 4.5 5개), 한도 시 회차를 다음 차수로 처음부터 다시 채점, 임베딩: Titan v2(us-east-1)
- contexts가 빈 문항(차단, 없는 정보, 정상만 있는 답 등)은 계산에서 빼고 그 수를 기록한다
"""
import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agent import MODEL_ORDER, _is_throttling, run_query  # noqa: E402

CSV_PATH = ROOT / "evaluation" / "test_queries.csv"
JUDGE_REGION, JUDGE_MODEL = MODEL_ORDER[0]  # 1차 (리전, 모델). 심판도 서비스와 같은 MODEL_ORDER를 쓴다
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_REGION = "us-east-1"
METRIC_NAMES = ["context_recall", "context_precision", "faithfulness", "answer_relevancy"]


CRITERIA = json.loads((ROOT / "data" / "criteria.json").read_text(encoding="utf-8"))


def _criteria_text(item: str) -> str:
    """criteria.json에서 항목의 판정 구간·출처를 한 문단으로 만든다."""
    spec = next((s for s in CRITERIA["항목"] if s["항목"] == item), None)
    if spec is None:
        return ""
    def bands(intervals):
        return ", ".join(f"{iv['구간']} {iv['원문표기']}" for iv in intervals)
    if spec["성별구분"]:
        body = " / ".join(f"{sex}성: {bands(ivs)}" for sex, ivs in spec["성별구간"].items())
    else:
        body = bands(spec["구간"])
    src = CRITERIA["출처"]
    note = f" 비고: {spec['비고']}." if spec.get("비고") else ""
    return (f"[판정 기준] {item}({spec['단위']}) {body}.{note} "
            f"출처: {src['기관']} 「{src['문서']}」, 기준일 {src['기준일']}.")


def _judgment_evidence(trace: list) -> list[str]:
    """trace의 코드 판정·계산 결과와 해당 항목의 판정 기준을 RAGAS 근거 문장으로 만든다.

    서비스 응답의 contexts(지침 검색 결과)는 그대로 두고, 평가할 때만 답의 실제 근거인
    코드 판정 결과(criteria.json)를 더한다.
    """
    texts = []
    for step in trace:
        name = step.get("step")
        if name not in ("judge_checkup_item", "calc_bmi"):
            continue
        try:
            r = json.loads(step["output"])
        except (TypeError, ValueError):
            continue
        if name == "calc_bmi":
            texts.append(f"[계산 결과] 체질량지수 = 몸무게(kg) ÷ 키(m)², 계산값 {r.get('bmi')} kg/m².")
            continue
        assume = f" 가정·환산: {'; '.join(r['assumptions'])}." if r.get("assumptions") else ""
        unit = r.get("unit") or ""
        if r.get("status") != "판정":
            texts.append(f"[판정 보류] {r.get('item')} {r.get('value')}{unit}: {r.get('reason', '')}{assume}")
            continue
        if r.get("by_sex"):
            result = ", ".join(f"{s} 기준 {v.get('band')}({v.get('range', '')})"
                               for s, v in r["by_sex"].items() if v.get("status") == "판정")
        else:
            result = f"{r.get('band')}({r.get('range', '')})"
        texts.append(f"[판정 결과] {r.get('item')} {r.get('value')}{unit} → {result}.{assume}")
        crit = _criteria_text(r.get("item", ""))
        if crit and crit not in texts:
            texts.append(crit)
    return texts


def collect_samples(rows: list) -> tuple[list, list]:
    """문항마다 run_query를 실행해 RAGAS 표본을 만들고, 근거가 하나도 없는 문항 id는 따로 모은다."""
    samples, excluded = [], []
    for row in rows:
        res = run_query(row["input"])
        guides = [c["text"] for c in res.get("contexts", []) if isinstance(c, dict) and c.get("text")]
        judged = _judgment_evidence(res.get("trace", []))
        texts = judged + guides
        if not texts:
            excluded.append(row["id"])
            continue
        samples.append({"id": row["id"], "user_input": row["input"], "response": str(res["answer"]),
                        "retrieved_contexts": texts, "reference": row["reference"],
                        "n_guides": len(guides), "n_judgment": len(judged)})
    return samples, excluded


def collect_queries(rows: list, out: Path) -> dict:
    """기준 설정으로 서비스를 한 번만 돌려 문항별 검색 질문문(retrieve_guides 단계 입력)을 JSON으로 저장한다.

    retrieve_guides를 한 번도 부르지 않은 문항은 비교에서 빼고 id를 기록한다.
    """
    queries, excluded = {}, []
    for row in rows:
        res = run_query(row["input"])
        qs = [t["input"] for t in res.get("trace", []) if t.get("step") == "retrieve_guides" and t.get("input")]
        if qs:
            queries[row["id"]] = qs
        else:
            excluded.append(row["id"])
        print(f"[질문문 수집] #{row['id']} 검색 {len(qs)}회", flush=True)
    payload = {"created_at": datetime.now().isoformat(timespec="seconds"),
               "baseline": {"k": 3, "rrf_weights": "keyword 1 : vector 1, 1/(60+순위)"},
               "total_questions": len(rows), "excluded_ids": excluded, "queries": queries}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"질문문 저장: {out} (제외 문항 {excluded})", flush=True)
    return payload


def score(samples: list, model_id: str = JUDGE_MODEL, region: str = JUDGE_REGION, retrieval_only: bool = False) -> list:
    """RAGAS 지표를 계산해 문항별 점수 목록을 돌려준다(retrieval_only면 검색 지표 둘만). 한도에 걸리면 ThrottlingException을 낸다."""
    from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall,
                               ResponseRelevancy)

    throttled: list = []

    class _FlagChat(ChatBedrockConverse):
        """ragas는 호출 오류를 NaN으로 삼키므로, 한도 오류를 따로 기록해 회차 끝에 다시 낸다."""

        def _generate(self, *a, **kw):
            try:
                return super()._generate(*a, **kw)
            except Exception as exc:
                if _is_throttling(exc):
                    throttled.append(exc)
                raise

        async def _agenerate(self, *a, **kw):
            try:
                return await super()._agenerate(*a, **kw)
            except Exception as exc:
                if _is_throttling(exc):
                    throttled.append(exc)
                raise

    llm = LangchainLLMWrapper(_FlagChat(model=model_id, region_name=region, temperature=0))
    emb = LangchainEmbeddingsWrapper(BedrockEmbeddings(model_id=EMBED_MODEL, region_name=EMBED_REGION))
    dataset = EvaluationDataset.from_list(
        [{k: s[k] for k in ("user_input", "response", "retrieved_contexts", "reference")} for s in samples])
    metrics = [LLMContextRecall(), LLMContextPrecisionWithReference()]
    if not retrieval_only:
        metrics += [Faithfulness(), ResponseRelevancy()]
    result = evaluate(dataset, metrics=metrics, llm=llm, embeddings=emb,
                      run_config=RunConfig(max_workers=4, timeout=180), show_progress=False)
    if throttled:
        raise throttled[0]
    return result.to_pandas().to_dict("records")


def build_retrieval_samples(rows: list, queries_path: Path, k: int, keyword_weight: float,
                            vector_weight: float, retriever=None, judge_model: str = JUDGE_MODEL) -> tuple[list, list]:
    """저장된 검색 질문문으로 검색 함수만 다시 실행해 RAGAS 표본을 만든다(서비스·답변 생성 없음).

    한 문항의 여러 질문문 결과는 doc_id 기준으로 중복 없이 합친다. 질문문이 없는 문항은 빼고 id를 돌려준다.
    retrieved_contexts에는 검색된 지침 조각만 넣는다.
    """
    if retriever is None:
        from src.retriever import retrieve_guides as retriever
    saved = json.loads(Path(queries_path).read_text(encoding="utf-8"))["queries"]
    samples, excluded = [], []
    for row in rows:
        qs = saved.get(row["id"])
        if not qs:
            excluded.append(row["id"])
            print(f"[검색 재실행] #{row['id']} 질문문 없음 → 제외 (채점 모델 {judge_model})", flush=True)
            continue
        merged: dict = {}
        for q in qs:
            chunks, _ = retriever(q, k, keyword_weight, vector_weight)
            for c in chunks:
                merged.setdefault(c["doc_id"], c)
        print(f"[검색 재실행] #{row['id']} 질문문 {len(qs)}개 → 근거 {len(merged)}개 "
              f"(k={k}, 키워드 {keyword_weight}:벡터 {vector_weight}, 채점 모델 {judge_model})", flush=True)
        if not merged:
            excluded.append(row["id"])
            continue
        samples.append({"id": row["id"], "user_input": row["input"], "response": "",
                        "retrieved_contexts": [c["text"] for c in merged.values()],
                        "reference": row["reference"], "doc_ids": list(merged)})
    return samples, excluded


def run_retrieval_round(rows: list, queries_path: Path, k: int, keyword_weight: float, vector_weight: float,
                        scorer=None, retriever=None) -> dict:
    """한 설정을 한 회차 재서 context_recall·context_precision만 돌려준다. NaN 문항이 있으면 회차를 무효로 표시한다."""
    samples, excluded = build_retrieval_samples(rows, queries_path, k, keyword_weight, vector_weight, retriever)
    base = scorer or (lambda s, m, r: score(s, m, r, retrieval_only=True))
    records, judge_model, judge_region = score_round(samples, base) if samples else ([], JUDGE_MODEL, JUDGE_REGION)
    alias = {"context_recall": "context_recall", "llm_context_precision_with_reference": "context_precision"}
    per_question = []
    for s, rec in zip(samples, records):
        row = {"id": s["id"], **{alias[a]: rec.get(a) for a in alias}}
        per_question.append(row)
        print(f"[채점] #{s['id']} recall={row['context_recall']} precision={row['context_precision']} "
              f"(채점 모델 {judge_model})", flush=True)
    summary, nan_ids = {}, []
    for name in ("context_recall", "context_precision"):
        summary[name] = dict(zip(("mean", "scored"), _mean([q.get(name) for q in per_question])))
    for q in per_question:
        if any(not isinstance(q.get(n), (int, float)) or math.isnan(q.get(n)) for n in alias.values()):
            nan_ids.append(q["id"])
    means = [summary[n]["mean"] for n in summary]
    return {"k": k, "keyword_weight": keyword_weight, "vector_weight": vector_weight,
            "judge_model": f"{judge_model} ({judge_region})", "evaluated": len(samples),
            "excluded_ids": excluded, "metrics": summary, "nan_ids": nan_ids, "valid": not nan_ids and bool(samples),
            "selection_score": round(sum(means) / 2, 4) if not nan_ids and None not in means else None,
            "per_question": per_question}


def score_round(samples: list, scorer=None) -> tuple[list, str, str]:
    """한 회차를 한 모델로만 채점한다. 한도에 걸리면 그 회차를 MODEL_ORDER의 다음 차수로 처음부터 다시 채점한다.

    돌려주는 값은 (문항별 점수, 채점 모델 ID, 채점 리전)이며, 넘어가면 앞 차수 결과는 버린다.
    한도가 아닌 오류는 넘기지 않고 올린다. 10개 차수가 모두 한도에 걸리면 마지막 예외를 올려 호출자가 멈추게 한다.
    """
    scorer = scorer or score
    for i, (region, model_id) in enumerate(MODEL_ORDER):
        try:
            return scorer(samples, model_id, region), model_id, region
        except Exception as exc:
            if not _is_throttling(exc) or i == len(MODEL_ORDER) - 1:
                raise
            nxt = MODEL_ORDER[i + 1]
            print(f"[채점 모델] {i + 1}차 한도 → {i + 2}차 {nxt[1]} ({nxt[0]})로 회차를 처음부터 다시 채점", flush=True)


def _mean(values: list):
    """NaN(계산 실패)을 뺀 평균과 계산된 문항 수를 돌려준다."""
    ok = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    return (round(sum(ok) / len(ok), 4) if ok else None), len(ok)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RAGAS 4개 지표를 측정해 저장한다")
    parser.add_argument("--out", default=str(ROOT / "evaluation" / "results" / "ragas_round2.json"))
    parser.add_argument("--collect-queries", metavar="경로", help="기준 설정으로 서비스를 한 번 돌려 검색 질문문만 JSON으로 저장하고 끝낸다")
    parser.add_argument("--retrieval-from", metavar="경로", help="저장된 검색 질문문으로 검색 함수만 다시 실행해 context_recall·context_precision만 잰다")
    parser.add_argument("--k", type=int, default=3, help="검색 조각 수 (--retrieval-from과 함께)")
    parser.add_argument("--keyword-weight", type=float, default=1.0, help="키워드 RRF 비중")
    parser.add_argument("--vector-weight", type=float, default=1.0, help="벡터 RRF 비중")
    args = parser.parse_args(argv)

    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.retrieval_from:
        result = run_retrieval_round(rows, Path(args.retrieval_from), args.k, args.keyword_weight, args.vector_weight)
        print(f"[요약] 채점 모델 {result['judge_model']} 유효={result['valid']} {result['metrics']}", flush=True)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"created_at": datetime.now().isoformat(timespec="seconds"), **result},
                                  ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"결과 저장: {out}", flush=True)
        return 0
    if args.collect_queries:
        collect_queries(rows, Path(args.collect_queries))
        return 0
    samples, excluded = collect_samples(rows)
    records, judge_model, judge_region = score_round(samples) if samples else ([], JUDGE_MODEL, JUDGE_REGION)
    print(f"[채점 모델] {judge_model} ({judge_region})", flush=True)

    # ragas 결과 열 이름(llm_context_precision_with_reference, answer_relevancy 등)을 제출 지표 이름으로 맞춘다
    alias = {"context_recall": "context_recall", "llm_context_precision_with_reference": "context_precision",
             "faithfulness": "faithfulness", "answer_relevancy": "answer_relevancy"}
    per_question = []
    for s, rec in zip(samples, records):
        per_question.append({"id": s["id"], **{alias[k]: rec.get(k) for k in alias if k in rec},
                             "contexts": len(s["retrieved_contexts"])})
    summary = {}
    for name in METRIC_NAMES:
        mean, n = _mean([q.get(name) for q in per_question])
        summary[name] = {"mean": mean, "scored": n}

    print(f"대상 {len(samples)}건, contexts 빈 문항 제외 {len(excluded)}건 ({', '.join('#' + i for i in excluded)})")
    for name, v in summary.items():
        print(f"  {name:<18} {v['mean']}  (계산 {v['scored']}건)")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": datetime.now().isoformat(timespec="seconds"),
               "judge_model": f"{judge_model} ({judge_region})", "embedding_model": f"{EMBED_MODEL} ({EMBED_REGION})",
               "total_questions": len(rows), "evaluated": len(samples),
               "excluded_empty_contexts": len(excluded), "excluded_ids": excluded,
               "metrics": summary, "per_question": per_question}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"결과 저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
