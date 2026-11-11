"""judge_checkup_item 경계값 단위 테스트: criteria.json 구간과 100% 일치하는지 전수 검증한다."""
import json
from pathlib import Path

import pytest

from src.tools import calc_bmi, judge_blood_pressure, judge_checkup_item

CRIT = json.loads((Path(__file__).resolve().parent.parent / "data" / "criteria.json").read_text(encoding="utf-8"))


def _cases():
    """criteria.json의 모든 구간 하한·상한과 그 직전 값을 만들어 기대 구간과 함께 돌려준다."""
    out = []
    for spec in CRIT["항목"]:
        groups = spec["성별구간"].items() if spec["성별구분"] else [(None, spec["구간"])]
        for sex, ivs in groups:
            rng = spec["허용범위"][sex] if "하한" not in spec["허용범위"] else spec["허용범위"]
            pts = set()
            for iv in ivs:
                for p in (iv["하한"], iv["상한"]):
                    if p is not None:
                        pts.update({p, round(p - 0.1, 1)})
            for p in sorted(pts):
                if not rng["하한"] <= p <= rng["상한"]:
                    continue
                exp = next((iv["구간"] for iv in ivs if p >= iv["하한"] and (iv["상한"] is None or p < iv["상한"])), None)
                out.append((spec["항목"], p, sex, exp))
    return out


@pytest.mark.parametrize("item,value,sex,exp", _cases())
def test_all_boundaries_match_criteria(item, value, sex, exp):
    r = judge_checkup_item(item, value, None, sex, True)
    assert (r["status"], r["band"]) == (("판정", exp) if exp else ("보류", None))


@pytest.mark.parametrize("v,exp", [(99.9, "정상"), (100, "경계"), (125.9, "경계"), (126, "질환의심")])
def test_fasting_glucose_spec_set(v, exp):
    assert judge_checkup_item("공복혈당", v, "mg/dL", None, True)["band"] == exp


def test_all_items_covered():
    assert len(CRIT["항목"]) == 13
    assert {c[0] for c in _cases()} == {i["항목"] for i in CRIT["항목"]}


def test_bmi_from_height_weight():
    b = calc_bmi(172, 81)
    assert b["bmi"] == 27.4
    assert judge_checkup_item("체질량지수", b["bmi"])["band"] == "경계"
    assert judge_checkup_item("체질량지수", calc_bmi(180, 97.2)["bmi"])["band"] == "질환의심"
    assert judge_checkup_item("체질량지수", calc_bmi(170, 50)["bmi"])["band"] == "경계"
    assert judge_checkup_item("체질량지수", calc_bmi(170, 60)["bmi"])["band"] == "정상"


def test_mmol_conversion_and_hold_rules():
    r = judge_checkup_item("공복혈당", 7.0, "mmol/L")
    assert r["band"] == "질환의심" and any("126" in a for a in r["assumptions"])
    assert "공복 가정" in r["assumptions"]
    assert judge_checkup_item("수축기 혈압", 900, "mmHg")["status"] == "보류"
    assert judge_checkup_item("수축기 혈압", 900, "mmHg")["band"] is None
    assert judge_checkup_item("수축기 혈압", 120, "kPa")["status"] == "보류"
    assert judge_checkup_item("AST", 30, "mmol/L")["status"] == "보류"
    assert judge_checkup_item("크레아티닌", 1.0)["status"] == "보류"


def test_sex_missing_gives_both():
    r = judge_checkup_item("허리둘레", 88)
    assert r["by_sex"]["남"]["band"] == "정상" and r["by_sex"]["여"]["band"] == "질환의심"


def test_blood_pressure_worse_side():
    assert judge_blood_pressure(118, 95)["overall_band"] == "질환의심"
    assert judge_blood_pressure(130, 70)["overall_band"] == "경계"


def test_hold_cases_have_no_band():
    """허용 범위 밖·미지원 단위·혈압 단일값·수치 없는 표기는 보류하고 구간을 쓰지 않는다."""
    cases = [
        judge_checkup_item("공복혈당", 5000, "mg/dL"),
        judge_checkup_item("총콜레스테롤", 200, "kPa"),
        judge_checkup_item("혈압", 130, "mmHg"),
        judge_checkup_item("공복혈당", "정상A"),
        judge_checkup_item("ALT", "주의"),
    ]
    for r in cases:
        assert r["status"] == "보류" and r["band"] is None and "range" not in r and "by_sex" not in r
        assert r["reason"]


def test_partial_hold_judges_others():
    """한 항목이 보류돼도 다른 항목 판정에는 영향이 없다."""
    rs = [judge_checkup_item("공복혈당", 5000), judge_checkup_item("수축기 혈압", 135, "mmHg"),
          judge_checkup_item("ALT", "정상B"), judge_checkup_item("LDL 콜레스테롤", 100)]
    assert [r["status"] for r in rs] == ["보류", "판정", "보류", "판정"]
    assert rs[1]["band"] == "경계"
