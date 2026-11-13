"""도메인 도구: 판정(judge_checkup_item), BMI 계산(calc_bmi). 수치 판정은 모두 코드가 한다."""
import json
import math
from pathlib import Path

CRITERIA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "criteria.json"
_CRITERIA = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
_ITEMS = {i["항목"]: i for i in _CRITERIA["항목"]}
_MMOL_FACTORS = _CRITERIA["지원단위"]["mmol/L 환산"]  # 키는 항목명 (HDL·LDL은 '… 콜레스테롤')
_BAND_ORDER = {"정상": 0, "경계": 1, "질환의심": 2}

_ALIASES = {
    "수축기혈압": "수축기 혈압", "이완기혈압": "이완기 혈압", "혈당": "공복혈당",
    "hdl": "HDL 콜레스테롤", "hdl콜레스테롤": "HDL 콜레스테롤",
    "ldl": "LDL 콜레스테롤", "ldl콜레스테롤": "LDL 콜레스테롤",
    "bmi": "체질량지수", "감마gtp": "감마지티피", "γ-gtp": "감마지티피", "ggt": "감마지티피",
    "ast": "AST", "alt": "ALT", "헤모글로빈": "혈색소", "콜레스테롤": "총콜레스테롤",
}
_AMBIGUOUS_BP = {"혈압", "bp", "bloodpressure"}  # 수축기/이완기 구분 없는 혈압 단일값
_SEX = {"남": "남", "남성": "남", "남자": "남", "m": "남", "male": "남",
        "여": "여", "여성": "여", "여자": "여", "f": "여", "female": "여"}


def _canon_item(item):
    """항목 이름(별칭 포함)을 criteria.json의 항목명으로 바꾼다. 모르면 None."""
    if not isinstance(item, str):
        return None
    key = item.strip()
    if key in _ITEMS:
        return key
    return _ALIASES.get(key.replace(" ", "").lower())


def _norm_unit(unit):
    """단위 표기를 비교용으로 정규화한다. 없으면 None."""
    if not isinstance(unit, str) or not unit.strip():
        return None
    return unit.strip().replace(" ", "").replace("㎎", "mg").lower()


def _find_band(intervals, value):
    """[하한 포함, 상한 미포함) 반개구간으로 구간을 찾는다."""
    for iv in intervals:
        if value >= iv["하한"] and (iv["상한"] is None or value < iv["상한"]):
            return iv
    return None


def _range_text(iv):
    lo, hi = iv["하한"], iv["상한"]
    if hi is None:
        return f"{lo:g} 이상"
    if lo == 0:
        return f"{hi:g} 미만"
    return f"{lo:g} 이상 {hi:g} 미만"


def _hold(item, value, unit, reason, assumptions, **extra):
    """보류 결과. 구간은 표기하지 않는다."""
    return {"status": "보류", "item": item, "value": value, "unit": unit, "band": None,
            "reason": reason, "assumptions": assumptions, **extra}


def _judge_one(spec, name, value, unit, sex, assumptions):
    """성별이 정해진(또는 불필요한) 항목 하나를 허용 범위 검사 후 판정한다."""
    rng = spec["허용범위"]
    if "하한" not in rng:
        rng = rng[sex]
    if not (rng["하한"] <= value <= rng["상한"]):
        return _hold(name, value, unit,
                     f"입력값이 허용 범위({rng['하한']:g}~{rng['상한']:g} {unit})를 벗어났습니다. 값을 다시 확인해 주세요.",
                     assumptions)
    intervals = spec["성별구간"][sex] if spec["성별구분"] else spec["구간"]
    iv = _find_band(intervals, value)
    if iv is None:
        return _hold(name, value, unit, "해당 구간을 찾지 못했습니다. 값을 다시 확인해 주세요.", assumptions)
    return {"status": "판정", "item": name, "value": value, "unit": unit, "band": iv["구간"],
            "range": _range_text(iv), "range_note": iv["원문표기"], "sex": sex,
            "assumptions": assumptions, "source": _CRITERIA["출처"]["기관"],
            "base_date": _CRITERIA["출처"]["기준일"]}


def judge_checkup_item(item, value, unit=None, sex=None, fasting=None):
    """검진 수치 하나를 정상/경계/질환의심으로 판정하거나 보류한다.

    사용: 질문에 검진 수치가 있을 때 항목마다 호출한다. 체질량지수는 calc_bmi 결과를 넣는다.
    비사용: 수치 없이 결과지 표기(정상A 등)만 있을 때, 지원하지 않는 검사 항목일 때.
    반환: status(판정/보류), band, range, assumptions 등. 성별 구분 항목에 성별이 없으면
    남녀 기준을 모두 담은 by_sex를 돌려준다.
    """
    if isinstance(item, str) and item.replace(" ", "").lower() in _AMBIGUOUS_BP:
        return _hold(item, value, unit, "혈압은 수축기(최고)와 이완기(최저) 값을 함께 알아야 합니다. "
                     "어느 쪽 값인지 알 수 없는 단일 수치는 판정하지 않습니다.", [])
    name = _canon_item(item)
    if name is None:
        return _hold(item, value, unit, "지원하지 않는 검사 항목입니다.", [], supported_items=list(_ITEMS))
    spec = _ITEMS[name]
    base_unit = spec["단위"]
    assumptions = []
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", ""))
        except ValueError:
            return _hold(name, value, unit, "수치 없이 결과지 표기(예: 정상A, 주의)만 있어 판정하지 않습니다. 측정 수치를 입력해 주세요.",
                         assumptions)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return _hold(name, value, unit, "수치를 숫자로 확인할 수 없습니다. 값을 다시 입력해 주세요.", assumptions)
    value = float(value)

    u = _norm_unit(unit)
    supported = [base_unit] + (["mmol/L"] if name in _MMOL_FACTORS else [])
    if u is None:
        assumptions.append(f"단위 미표기: {base_unit}로 가정")
    elif u == "mmol/l" and name in _MMOL_FACTORS:
        converted = round(value * _MMOL_FACTORS[name], 2)
        assumptions.append(
            f"mmol/L → mg/dL 환산: {value:g} mmol/L × {_MMOL_FACTORS[name]:g} = {converted:g} mg/dL")
        value = converted
    elif u != base_unit.lower():
        return _hold(name, value, unit, f"지원하지 않는 단위입니다. 지원 단위: {', '.join(supported)}",
                     assumptions, supported_units=supported)

    if name == "공복혈당":
        if fasting is False:
            return _hold(name, value, base_unit, "공복 상태가 아닌 혈당은 공복혈당 기준으로 판정할 수 없습니다.",
                         assumptions)
        if fasting is None:
            assumptions.append("공복 가정")

    if spec["성별구분"]:
        s = _SEX.get(str(sex).strip().lower()) if sex is not None else None
        if s is None:
            by_sex = {k: _judge_one(spec, name, value, base_unit, k, list(assumptions)) for k in ("남", "여")}
            if all(r["status"] == "보류" for r in by_sex.values()):
                return _hold(name, value, base_unit, by_sex["남"]["reason"], assumptions)
            assumptions.append("성별 미입력: 남녀 기준 모두 제시")
            return {"status": "판정", "item": name, "value": value, "unit": base_unit, "band": None,
                    "by_sex": by_sex, "assumptions": assumptions,
                    "source": _CRITERIA["출처"]["기관"], "base_date": _CRITERIA["출처"]["기준일"]}
        return _judge_one(spec, name, value, base_unit, s, assumptions)
    return _judge_one(spec, name, value, base_unit, None, assumptions)


def worse_band(*bands):
    """여러 구간 중 더 나쁜 쪽을 고른다(혈압 결합 규칙)."""
    return max(bands, key=lambda b: _BAND_ORDER[b])


def judge_blood_pressure(systolic, diastolic):
    """수축기·이완기를 각각 판정하고 더 나쁜 쪽 구간을 종합 구간으로 돌려준다."""
    s = judge_checkup_item("수축기 혈압", systolic, "mmHg")
    d = judge_checkup_item("이완기 혈압", diastolic, "mmHg")
    overall = None
    if s["status"] == "판정" and d["status"] == "판정":
        overall = worse_band(s["band"], d["band"])
    return {"systolic": s, "diastolic": d, "overall_band": overall}


def calc_bmi(height_cm, weight_kg):
    """키(cm)와 몸무게(kg)로 체질량지수를 계산한다(소수 첫째 자리 반올림). 구간 판정은 judge_checkup_item이 한다."""
    ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0
             for v in (height_cm, weight_kg))
    if not ok:
        return {"status": "보류", "bmi": None, "reason": "키와 몸무게를 양수로 입력해 주세요."}
    bmi = round(weight_kg / (height_cm / 100) ** 2, 1)
    return {"status": "계산", "bmi": bmi, "height_cm": height_cm, "weight_kg": weight_kg}
