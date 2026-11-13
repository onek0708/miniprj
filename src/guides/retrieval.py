"""RAG 파이프라인 (패턴 3): 지침 문서를 헤더 단위로 쪼개 하이브리드(키워드 + 벡터) 검색한다.

벡터 검색(Chroma + Titan 임베딩)이 실패하면 키워드 검색만으로 계속하고,
둘 다 결과가 없으면 빈 목록을 돌려준다 (호출 쪽이 "근거 지침 없음"을 안내).
"""
import re
from pathlib import Path
from typing import Optional

GUIDES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "guides"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
REGION = "us-east-1"
# 고른 검색 설정의 기본값 (인자를 주지 않으면 이 값을 쓴다). 비교 결과는 evaluation/round2_report.md 참고.
DEFAULT_K = 3
DEFAULT_KEYWORD_WEIGHT = 1.0
DEFAULT_VECTOR_WEIGHT = 1.0
_chunks_cache: Optional[list] = None
_vector_store = None


def load_chunks() -> list[dict]:
    """`## 헤더` 하나를 조각 하나로 만든다. doc_id는 `guides/파일명#헤더`, item·topic 메타데이터를 붙인다."""
    global _chunks_cache
    if _chunks_cache is not None:
        return _chunks_cache
    chunks = []
    for path in sorted(GUIDES_DIR.glob("*.md")):
        header, lines = None, []
        for line in path.read_text(encoding="utf-8").splitlines() + ["## "]:
            if line.startswith("## "):
                if header and lines:
                    item, _, topic = (p.strip() for p in header.partition(" - "))
                    chunks.append({"doc_id": f"guides/{path.name}#{header}", "item": item,
                                   "topic": topic, "text": "\n".join(lines).strip()})
                header, lines = line[3:].strip(), []
            elif header:
                lines.append(line)
    _chunks_cache = chunks
    return chunks


def guide_source(doc_id: str) -> str:
    """doc_id(`guides/파일명#헤더`)의 지침 문서 머리말에서 출처와 확인 날짜를 읽어 한 줄로 돌려준다."""
    name = doc_id.split("#")[0].split("/")[-1]
    src = date = ""
    try:
        for line in (GUIDES_DIR / name).read_text(encoding="utf-8").splitlines()[:10]:
            if line.startswith("출처:"):
                src = line.split(":", 1)[1].strip()
            elif line.startswith("확인 날짜:"):
                date = line.split(":", 1)[1].strip().split()[0]
    except OSError:
        pass
    return f"{doc_id} — {src or '출처 미상'}" + (f" (확인 {date})" if date else "")


def _tokens(text: str) -> set:
    """공백 단어와 한글 2글자 조각을 함께 쓴다 (조사가 붙어도 매칭되도록)."""
    words = re.findall(r"[0-9A-Za-z가-힣]+", text.lower())
    grams = {w[i:i + 2] for w in words for i in range(len(w) - 1)}
    return set(words) | grams


def keyword_search(query: str, k: int = 4) -> list[dict]:
    """키워드 검색: 질문과 조각(헤더 포함)의 토큰 겹침 점수."""
    q = _tokens(query)
    scored = []
    for c in load_chunks():
        score = len(q & _tokens(c["doc_id"].split("#")[1] + " " + c["text"]))
        if score:
            scored.append((score, c))
    scored.sort(key=lambda s: -s[0])
    return [c for _, c in scored[:k]]


def _get_vector_store():
    global _vector_store
    if _vector_store is None:
        from dotenv import load_dotenv
        from langchain_aws import BedrockEmbeddings
        from langchain_chroma import Chroma
        load_dotenv()
        store = Chroma(collection_name="guides",
                       embedding_function=BedrockEmbeddings(model_id=EMBED_MODEL, region_name=REGION))
        chunks = load_chunks()
        store.add_texts([c["text"] for c in chunks], ids=[c["doc_id"] for c in chunks],
                        metadatas=[{"doc_id": c["doc_id"]} for c in chunks])
        _vector_store = store
    return _vector_store


def vector_search(query: str, k: int = 4) -> list[dict]:
    """벡터 검색. 실패하면 예외를 그대로 던진다."""
    by_id = {c["doc_id"]: c for c in load_chunks()}
    docs = _get_vector_store().similarity_search(query, k=k)
    return [by_id[d.metadata["doc_id"]] for d in docs if d.metadata.get("doc_id") in by_id]


def hybrid_search(query: str, k: int = DEFAULT_K,
                  keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
                  vector_weight: float = DEFAULT_VECTOR_WEIGHT) -> tuple[list[dict], dict]:
    """두 검색 결과를 가중 RRF(비중 × 1/(60+순위))로 합친다. (조각 목록, 검색 상태)를 돌려준다."""
    status = {"keyword": "ok", "vector": "ok"}
    lists = [keyword_search(query, k * 2)]
    weights = [keyword_weight]
    try:
        lists.append(vector_search(query, k * 2))
        weights.append(vector_weight)
    except Exception as exc:  # Chroma·임베딩 실패는 키워드 검색으로 대체
        status["vector"] = f"실패({type(exc).__name__})"
    scores: dict = {}
    for ranked, weight in zip(lists, weights):
        for rank, c in enumerate(ranked):
            scores[c["doc_id"]] = scores.get(c["doc_id"], 0) + weight / (60 + rank)
    by_id = {c["doc_id"]: c for r in lists for c in r}
    top = sorted(scores, key=lambda d: -scores[d])[:k]
    return [by_id[d] for d in top], status


def retrieve_guides(query: str, k: int = DEFAULT_K,
                    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
                    vector_weight: float = DEFAULT_VECTOR_WEIGHT) -> tuple[list[dict], dict]:
    """지침 검색 진입점. 검색 전체가 실패해도 예외 없이 빈 목록을 돌려준다."""
    try:
        return hybrid_search(query, k, keyword_weight, vector_weight)
    except Exception as exc:
        return [], {"keyword": f"실패({type(exc).__name__})", "vector": "건너뜀"}
