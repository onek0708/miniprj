"""POST /query 진입점."""
from fastapi import FastAPI, Request

from src.agent import run_query

app = FastAPI(title="건강검진 수치 해석 어시스턴트")


@app.post("/query")
async def query(request: Request) -> dict:
    """Body {"question": "..."}를 받아 상태 코드와 무관하게 세 키 응답을 돌려준다."""
    try:
        body = await request.json()
        question = body.get("question") if isinstance(body, dict) else None
    except Exception:  # 잘못된 JSON 형식
        question = None
    return run_query(question)
