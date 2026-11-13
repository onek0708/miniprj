"""여러 도메인이 함께 쓰는 LLM 설정: 모델 순서, 한도 오류 판별, 모델 생성."""

# 모델 순서(리전, 모델 ID): 1~5차 Sonnet 4.6, 6~10차 Sonnet 4.5. 서비스와 RAGAS 심판이 이 목록 하나를 함께 쓴다.
MODEL_ORDER = [
    ("us-west-2", "us.anthropic.claude-sonnet-4-6"),
    ("us-west-2", "global.anthropic.claude-sonnet-4-6"),
    ("us-east-1", "us.anthropic.claude-sonnet-4-6"),
    ("us-east-1", "global.anthropic.claude-sonnet-4-6"),
    ("ap-northeast-2", "global.anthropic.claude-sonnet-4-6"),
    ("us-west-2", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("us-west-2", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("us-east-1", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("us-east-1", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("ap-northeast-2", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
]


def _is_throttling(exc: BaseException) -> bool:
    """Bedrock 한도(ThrottlingException) 오류인지 확인한다."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "") if hasattr(exc, "response") else ""
    return "ThrottlingException" in (code, type(exc).__name__) or "ThrottlingException" in str(exc)


def build_chat_model(model_id: str, region: str):
    """지정한 (리전, 모델)의 Bedrock 채팅 모델을 만든다. temperature=0으로 답 흔들림을 줄인다."""
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(model=model_id, region_name=region, temperature=0)
