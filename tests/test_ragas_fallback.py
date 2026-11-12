"""RAGAS 채점 회차 단위 10단계 모델 순서 전환 검증 (실제 Bedrock 호출 없음)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation"))
import run_ragas  # noqa: E402
from src import agent  # noqa: E402


class ThrottlingException(Exception):
    pass


def test_심판도_서비스와_같은_모델_순서를_씀():
    assert run_ragas.MODEL_ORDER is agent.MODEL_ORDER
    assert (run_ragas.JUDGE_REGION, run_ragas.JUDGE_MODEL) == agent.MODEL_ORDER[0]


def test_1차_성공시_넘어가지_않음():
    calls = []
    def scorer(samples, model, region):
        calls.append((region, model))
        return [{"ok": 1}]
    recs, model, region = run_ragas.score_round([{}], scorer)
    assert calls == [agent.MODEL_ORDER[0]] and (region, model) == agent.MODEL_ORDER[0]


def test_한도시_회차를_다음_차수로_처음부터_다시_채점():
    calls = []
    def scorer(samples, model, region):
        calls.append((region, model))
        if len(calls) <= 5:
            raise ThrottlingException("Too many tokens")
        return [{"from": model}]
    recs, model, region = run_ragas.score_round([{}], scorer)
    assert calls == agent.MODEL_ORDER[:6]
    assert (region, model) == agent.MODEL_ORDER[5] and recs == [{"from": model}]


def test_한도가_아닌_오류는_전환하지_않음():
    def scorer(samples, model, region):
        raise ValueError("다른 오류")
    with pytest.raises(ValueError):
        run_ragas.score_round([{}], scorer)


def test_10개_모두_한도면_예외를_올림():
    calls = []
    def scorer(samples, model, region):
        calls.append((region, model))
        raise ThrottlingException("limit")
    with pytest.raises(ThrottlingException):
        run_ragas.score_round([{}], scorer)
    assert calls == agent.MODEL_ORDER
