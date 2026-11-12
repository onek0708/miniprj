"""하이브리드 검색의 RRF 가중치 인자 테스트 (실제 Bedrock 호출 없음)."""
import inspect

from src import retriever


def _c(name):
    return {"doc_id": f"guides/x.md#{name}", "item": name, "topic": "", "text": name}


def _patch(monkeypatch):
    monkeypatch.setattr(retriever, "keyword_search", lambda q, k=4: [_c("A"), _c("B")])
    monkeypatch.setattr(retriever, "vector_search", lambda q, k=4: [_c("B"), _c("A")])


def _first(result):
    return result[0][0]["item"]


def test_가중치_기본값은_같은_비중(monkeypatch):
    _patch(monkeypatch)
    assert retriever.DEFAULT_KEYWORD_WEIGHT == retriever.DEFAULT_VECTOR_WEIGHT
    for fn in (retriever.hybrid_search, retriever.retrieve_guides):
        params = inspect.signature(fn).parameters
        assert params["keyword_weight"].default == retriever.DEFAULT_KEYWORD_WEIGHT
        assert params["vector_weight"].default == retriever.DEFAULT_VECTOR_WEIGHT
    # 같은 비중이면 1순위 A·B 점수가 같아 정렬이 안정적으로 먼저 나온 A
    assert _first(retriever.hybrid_search("q")) == "A"


def test_키워드_비중이_크면_키워드_1순위(monkeypatch):
    _patch(monkeypatch)
    assert _first(retriever.hybrid_search("q", 2, 0.7, 0.3)) == "A"
    assert _first(retriever.retrieve_guides("q", 2, keyword_weight=0.7, vector_weight=0.3)) == "A"


def test_벡터_비중이_크면_벡터_1순위(monkeypatch):
    _patch(monkeypatch)
    assert _first(retriever.hybrid_search("q", 2, 0.3, 0.7)) == "B"
    assert _first(retriever.retrieve_guides("q", 2, keyword_weight=0.3, vector_weight=0.7)) == "B"
