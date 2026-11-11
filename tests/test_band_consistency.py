"""판정은 코드만: 답의 구간 표기는 trace의 judge_checkup_item 결과와 같고, 보류 항목에는 구간을 쓰지 않는다."""
import json

import pytest

from src import agent
from src.tools import judge_checkup_item


def _trace(*results):
    return [{"step": "judge_checkup_item", "input": "{}", "output": json.dumps(r, ensure_ascii=False)}
            for r in results]


def test_wrong_band_is_replaced_by_code_result():
    r = judge_checkup_item("공복혈당", 130, "mg/dL")
    out = agent.ensure_band_consistency("공복혈당 130 mg/dL는 정상입니다.\n생활습관을 관리하세요.", _trace(r))
    assert "정상" not in out
    assert "질환의심" in out and "생활습관을 관리하세요." in out


def test_correct_band_line_is_kept():
    r = judge_checkup_item("공복혈당", 110, "mg/dL")
    ans = "공복혈당 110 mg/dL는 경계 구간입니다."
    assert agent.ensure_band_consistency(ans, _trace(r)) == ans


def test_hold_item_band_is_removed():
    r = judge_checkup_item("공복혈당", 9999, "mg/dL")
    assert r["status"] == "보류"
    out = agent.ensure_band_consistency("공복혈당 9999는 질환의심입니다.", _trace(r))
    assert "질환의심" not in out and "보류" in out


def test_hold_line_mentioning_hold_is_kept():
    r = judge_checkup_item("공복혈당", 9999, "mg/dL")
    ans = "공복혈당은 정상 여부를 판정할 수 없어 보류합니다."
    assert agent.ensure_band_consistency(ans, _trace(r)) == ans


def test_sex_split_wrong_band_replaced():
    r = judge_checkup_item("혈색소", 8.0, "g/dL")
    out = agent.ensure_band_consistency("혈색소 8.0은 정상입니다.", _trace(r))
    assert "정상" not in out and "남 기준" in out and "여 기준" in out


def test_blood_pressure_alias_line():
    r = judge_checkup_item("수축기 혈압", 150, "mmHg")
    out = agent.ensure_band_consistency("수축기 150은 정상입니다.", _trace(r))
    assert "정상" not in out and r["band"] in out


@pytest.mark.parametrize("item,val,unit", [("공복혈당", 99.9, "mg/dL"), ("공복혈당", 100, "mg/dL"),
                                           ("공복혈당", 125.9, "mg/dL"), ("공복혈당", 126, "mg/dL")])
def test_every_wrong_claim_is_fixed(item, val, unit):
    r = judge_checkup_item(item, val, unit)
    for wrong in ("정상", "경계", "질환의심"):
        if wrong == r["band"]:
            continue
        out = agent.ensure_band_consistency(f"{item}은 {wrong}입니다.", _trace(r))
        assert wrong not in out and r["band"] in out


def test_no_judge_results_leaves_answer():
    assert agent.ensure_band_consistency("정상입니다.", []) == "정상입니다."
