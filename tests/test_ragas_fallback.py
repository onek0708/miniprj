"""RAGAS 채점 회차 단위 예비 모델 전환 검증 (실제 Bedrock 호출 없음)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation"))
import run_ragas  # noqa: E402


class ThrottlingException(Exception):
    pass


def test_모델_설정():
    assert run_ragas.JUDGE_MODEL == "us.anthropic.claude-sonnet-4-6"
    assert run_ragas.JUDGE_FALLBACK_MODEL == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert run_ragas.JUDGE_REGION == "us-west-2"


def test_주_모델_성공시_예비_모델_안_부름():
    calls = []
    def scorer(samples, model):
        calls.append(model)
        return [{"ok": 1}]
    recs, model = run_ragas.score_round([{}], scorer)
    assert calls == [run_ragas.JUDGE_MODEL] and model == run_ragas.JUDGE_MODEL


def test_한도시_회차를_예비_모델로_처음부터_다시_채점():
    calls = []
    def scorer(samples, model):
        calls.append(model)
        if model == run_ragas.JUDGE_MODEL:
            raise ThrottlingException("Too many tokens")
        return [{"from": model}]
    recs, model = run_ragas.score_round([{}], scorer)
    assert calls == [run_ragas.JUDGE_MODEL, run_ragas.JUDGE_FALLBACK_MODEL]
    assert model == run_ragas.JUDGE_FALLBACK_MODEL and recs == [{"from": model}]


def test_한도가_아닌_오류는_전환하지_않음():
    def scorer(samples, model):
        raise ValueError("다른 오류")
    with pytest.raises(ValueError):
        run_ragas.score_round([{}], scorer)


def test_두_모델_모두_한도면_예외를_올림():
    def scorer(samples, model):
        raise ThrottlingException("limit")
    with pytest.raises(ThrottlingException):
        run_ragas.score_round([{}], scorer)
