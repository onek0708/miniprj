"""응답 도메인의 API 응답 스키마."""
from pydantic import BaseModel


class QueryResponse(BaseModel):
    """POST /query 응답 스키마 (제출 규약: answer, contexts, trace)."""
    answer: str
    contexts: list
    trace: list[dict]
