"""LLM-as-Judge: 표현형 금지 항목과 문장 성격 항목을 AI가 판정한다 (역할: judge 호출과 응답 해석)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import agent  # noqa: E402


def build_prompt(question: str, answer: str, forbidden: list, traits: list) -> str:
    """질문·answer·체크리스트만 담은 judge 프롬프트를 만든다. 정답(reference)은 받지도 넣지도 않는다."""
    lines = ["너는 건강검진 안내 답변의 채점자다. 아래 답변이 각 항목에 해당하는지 판정하라.",
             f"[질문]\n{question}", f"[답변]\n{answer}", "[금지 항목] 답변에 이 표현이 있으면 violated=true"]
    lines += [f"F{i}. {t}" for i, t in enumerate(forbidden, 1)] or ["(없음)"]
    lines.append("[충족 항목] 답변에 이 성격이 있으면 met=true")
    lines += [f"T{i}. {t}" for i, t in enumerate(traits, 1)] or ["(없음)"]
    lines.append('JSON만 출력하라: {"forbidden": [{"id": "F1", "violated": false, "reason": ""}], '
                 '"traits": [{"id": "T1", "met": true, "reason": ""}]}')
    return "\n\n".join(lines)


def parse_verdicts(raw: str):
    """judge 원문에서 JSON 판정을 꺼낸다. 해석할 수 없으면 None."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _make_model(region: str, model_id: str):
    """Bedrock judge 모델을 temperature 0으로 만든다."""
    from dotenv import load_dotenv
    from langchain_aws import ChatBedrockConverse

    load_dotenv()
    return ChatBedrockConverse(model=model_id, region_name=region, temperature=0)


def judge(question: str, answer: str, forbidden: list, traits: list, model_factory=None) -> dict:
    """MODEL_ORDER 순서로 judge를 1번 호출한다. 한도(ThrottlingException)일 때만 다음 차수로 넘기고 다른 예외는 그대로 올린다.

    돌려주는 값: raw(원문), verdicts(해석 결과 또는 None), model(답한 리전·모델 ID).
    """
    make = model_factory or _make_model
    prompt = build_prompt(question, answer, forbidden, traits)
    last_exc = None
    for tier in agent.MODEL_ORDER:
        region, model_id = tier
        try:
            reply = make(region, model_id).invoke(prompt)
        except Exception as exc:
            if not agent._is_throttling(exc):
                raise
            last_exc = exc
            continue
        raw = reply.text if hasattr(reply, "text") and not callable(reply.text) else str(getattr(reply, "content", reply))
        return {"raw": raw, "verdicts": parse_verdicts(raw), "model": {"region": region, "model_id": model_id}}
    raise last_exc or RuntimeError("ThrottlingException: 10개 모델 차수가 모두 한도에 걸려 있습니다")
