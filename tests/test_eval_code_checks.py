"""평가 코드 검사: expected_tools 누락과 진료 권고 키워드 누락 검출."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation"))
import run_eval  # noqa: E402


def _step(name, output=""):
    return {"step": name, "input": "", "output": output}


def test_expected_tools_all_present():
    trace = [_step("judge_checkup_item"), _step("retrieve_guides")]
    assert run_eval.check_expected_tools(trace, "judge_checkup_item;retrieve_guides") == []


def test_expected_tools_missing_detected():
    fails = run_eval.check_expected_tools([_step("judge_checkup_item")], "judge_checkup_item;calc_bmi")
    assert fails == ["도구 호출 누락: calc_bmi"]


def test_expected_tools_empty_means_no_check():
    assert run_eval.check_expected_tools([], "") == []


def test_referral_missing_detected():
    trace = [_step("judge_checkup_item", json.dumps({"band": "질환의심"}))]
    assert run_eval.check_referral("수치가 높습니다.", trace)


def test_referral_missing_detected_nested_by_sex():
    out = {"by_sex": {"남": {"band": "정상"}, "여": {"band": "질환의심"}}}
    assert run_eval.check_referral("낮습니다.", [_step("judge_checkup_item", json.dumps(out))])


def test_referral_present_passes():
    trace = [_step("judge_checkup_item", json.dumps({"band": "질환의심"}))]
    assert run_eval.check_referral("병원에서 진료를 받으세요.", trace) == []


def test_referral_not_required_without_suspect():
    trace = [_step("judge_checkup_item", json.dumps({"band": "경계"}))]
    assert run_eval.check_referral("경계입니다.", trace) == []


def _csv_rows():
    import csv
    with open(run_eval.CSV_PATH, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_assignment_table_covers_all_forbidden_values():
    """forbidden 값 33개가 모두 배정 표에 있고 방식이 code 또는 judge다."""
    values = [v for r in _csv_rows() for v in run_eval.split_values(r["forbidden"])]
    assert len(values) == 33
    for v in values:
        assert run_eval.FORBIDDEN_ASSIGNMENT[v][0] in ("code", "judge"), v


def test_assignment_table_covers_all_sentence_traits():
    """문장 성격 trait 값 31개(18종)가 모두 배정 표에 있다."""
    values = [v for r in _csv_rows() for v in run_eval.split_values(r["expected_traits"]) if not v.startswith("구간:")]
    assert len(values) == 31 and len(set(values)) == 18
    for v in values:
        assert run_eval.TRAIT_ASSIGNMENT[v][0] in ("code", "judge"), v


def test_assignment_table_has_no_unused_entries():
    rows = _csv_rows()
    f = {v for r in rows for v in run_eval.split_values(r["forbidden"])}
    t = {v for r in rows for v in run_eval.split_values(r["expected_traits"]) if not v.startswith("구간:")}
    assert set(run_eval.FORBIDDEN_ASSIGNMENT) == f and set(run_eval.TRAIT_ASSIGNMENT) == t


def test_code_assigned_traits_have_pattern():
    for v, (kind, _) in run_eval.TRAIT_ASSIGNMENT.items():
        assert (v in run_eval.TRAIT_CODE_PATTERNS) == (kind == "code"), v


def test_check_code_traits_detects_missing():
    assert run_eval.check_code_traits("BMI 27.4입니다.", "체질량지수 27.4 표기") == []
    assert run_eval.check_code_traits("BMI입니다.", "체질량지수 27.4 표기") == ["특성 누락: 체질량지수 27.4 표기"]


def test_judge_criteria_splits_by_assignment():
    row = {"expected_traits": "구간:공복혈당=경계; 출처 표기; 생활습관 지침", "forbidden": "당뇨병 단정; 약 이름"}
    assert run_eval.judge_criteria(row) == [("forbidden", "당뇨병 단정"), ("trait", "생활습관 지침")]


# ---- judge 결과 처리 (가짜 judge, 실제 Bedrock 호출 없음) ----
import csv  # noqa: E402


def _row_with_judge():
    rows = list(csv.DictReader(open(run_eval.CSV_PATH, encoding="utf-8", newline="")))
    return next(r for r in rows if run_eval.judge_criteria(r))


def _patch_run_query(monkeypatch, row):
    ans = "측정값 안내입니다. " + run_eval.DISCLAIMER
    monkeypatch.setattr(run_eval, "run_query", lambda q: {"answer": ans, "contexts": [], "trace": []})


def _fake(status, verdict="충족"):
    def judge(question, answer, labels):
        v = [{"criterion": c, "verdict": verdict, "reason": "근거"} for c in labels]
        return {"status": status, "verdicts": v if status == "판정" else [], "model": "m", "region": "r", "error": "해석 불가" if status != "판정" else ""}
    return judge


def test_judge_violation_counts_as_failure(monkeypatch):
    row = _row_with_judge()
    _patch_run_query(monkeypatch, row)
    res = run_eval.apply_judge(row, "답", _fake("판정", "위반"))
    assert res["judge_failures"] and not res["needs_human_check"]
    assert res["judge_model"] == "m" and res["judge_region"] == "r" and res["judge_verdicts"]


def test_judge_unjudgeable_is_human_check_not_failure():
    row = _row_with_judge()
    res = run_eval.apply_judge(row, "답", _fake("판정불가"))
    assert res["needs_human_check"] and res["judge_failures"] == []
    assert res["judge_error"]


def test_evaluate_row_records_judge_fields(monkeypatch):
    row = _row_with_judge()
    _patch_run_query(monkeypatch, row)
    r = run_eval.evaluate_row(row, judge=_fake("판정", "위반"))
    assert any(f.startswith("judge 위반") for f in r["failures"]) and not r["passed"]
    assert r["judge_verdicts"] and r["judge_model"] == "m"
    r2 = run_eval.evaluate_row(row, judge=_fake("판정불가"))
    assert r2["needs_human_check"] is True
    assert not any(f.startswith("judge 위반") for f in r2["failures"])
