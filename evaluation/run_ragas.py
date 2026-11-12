"""RAGAS 평가 스크립트: test_queries.csv 20건을 run_query로 돌려 RAGAS 4개 지표를 측정하고 JSON으로 저장한다.

사용법: python evaluation/run_ragas.py [--out 경로]
- 지표: context_recall, context_precision, faithfulness, answer_relevancy (측정만, 통과 기준 없음)
- 심판 모델: 서비스와 같은 Sonnet 4.6(ap-northeast-2), 임베딩: Titan v2(us-east-1)
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

from src.agent import run_query  # noqa: E402

CSV_PATH = ROOT / "evaluation" / "test_queries.csv"
JUDGE_MODEL = "global.anthropic.claude-sonnet-4-6"
JUDGE_REGION = "ap-northeast-2"
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


def score(samples: list) -> list:
    """RAGAS 4개 지표를 계산해 문항별 점수 목록을 돌려준다."""
    from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall,
                               ResponseRelevancy)

    llm = LangchainLLMWrapper(ChatBedrockConverse(model=JUDGE_MODEL, region_name=JUDGE_REGION, temperature=0))
    emb = LangchainEmbeddingsWrapper(BedrockEmbeddings(model_id=EMBED_MODEL, region_name=EMBED_REGION))
    dataset = EvaluationDataset.from_list(
        [{k: s[k] for k in ("user_input", "response", "retrieved_contexts", "reference")} for s in samples])
    metrics = [LLMContextRecall(), LLMContextPrecisionWithReference(), Faithfulness(), ResponseRelevancy()]
    result = evaluate(dataset, metrics=metrics, llm=llm, embeddings=emb,
                      run_config=RunConfig(max_workers=4, timeout=180), show_progress=False)
    return result.to_pandas().to_dict("records")


def _mean(values: list):
    """NaN(계산 실패)을 뺀 평균과 계산된 문항 수를 돌려준다."""
    ok = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    return (round(sum(ok) / len(ok), 4) if ok else None), len(ok)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RAGAS 4개 지표를 측정해 저장한다")
    parser.add_argument("--out", default=str(ROOT / "evaluation" / "results" / "ragas_round2.json"))
    args = parser.parse_args(argv)

    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    samples, excluded = collect_samples(rows)
    records = score(samples) if samples else []

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
               "judge_model": f"{JUDGE_MODEL} ({JUDGE_REGION})", "embedding_model": f"{EMBED_MODEL} ({EMBED_REGION})",
               "total_questions": len(rows), "evaluated": len(samples),
               "excluded_empty_contexts": len(excluded), "excluded_ids": excluded,
               "metrics": summary, "per_question": per_question}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"결과 저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
