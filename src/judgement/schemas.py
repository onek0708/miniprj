"""판정 도메인의 도구 출력 스키마 (패턴 1: 구조화 출력)."""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class JudgeOutput(BaseModel):
    """judge_checkup_item 결과 스키마 (패턴 1: 구조화 출력). 성별 구분 항목은 by_sex에 남녀 결과를 담는다."""
    model_config = ConfigDict(extra="allow")
    status: Literal["판정", "보류"]
    item: str
    band: Optional[Literal["정상", "경계", "질환의심"]] = None
    assumptions: list[str] = []


class BmiOutput(BaseModel):
    """calc_bmi 결과 스키마."""
    model_config = ConfigDict(extra="allow")
    status: Literal["계산", "보류"]
    bmi: Optional[float] = None
