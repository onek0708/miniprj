"""질환의심 진료 안내 (G3): 질환의심 판정이 하나라도 있으면 답에 의료기관 진료 안내가 있다."""
import json

from src import agent
from src.tools import judge_checkup_item


def _trace(*results):
    return [{"step": "judge_checkup_item", "input": "{}", "output": json.dumps(r, ensure_ascii=False)}
            for r in results]


def test_referral_appended_for_suspect():
    out = agent.ensure_referral("공복혈당은 질환의심입니다.", _trace(judge_checkup_item("공복혈당", 130, "mg/dL")))
    assert agent.REFERRAL_NOTICE in out


def test_referral_appended_for_sex_split_suspect():
    r = judge_checkup_item("혈색소", 8.0, "g/dL")
    assert "by_sex" in r
    assert agent.REFERRAL_NOTICE in agent.ensure_referral("수치가 낮습니다.", _trace(r))


def test_referral_when_only_one_of_many_suspect():
    t = _trace(judge_checkup_item("공복혈당", 90, "mg/dL"), judge_checkup_item("총콜레스테롤", 260, "mg/dL"))
    assert agent.REFERRAL_NOTICE in agent.ensure_referral("결과입니다.", t)


def test_no_duplicate_when_already_advised():
    t = _trace(judge_checkup_item("공복혈당", 130, "mg/dL"))
    ans = "질환의심입니다. 병원 진료를 받으세요."
    assert agent.ensure_referral(ans, t) == ans


def test_no_referral_for_normal_or_hold():
    t = _trace(judge_checkup_item("공복혈당", 90, "mg/dL"), judge_checkup_item("공복혈당", 9999, "mg/dL"))
    assert agent.ensure_referral("정상입니다.", t) == "정상입니다."
