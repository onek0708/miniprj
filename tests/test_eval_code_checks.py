"""run_eval의 코드 검사(expected_tools, 진료 권고) 단위 테스트: 가짜 trace·answer로 통과·실패를 확인한다."""
import json

from evaluation.run_eval import check_expected_tools, check_referral


def _judge(band=None, by_sex=None):
    """judge_checkup_item 단계 하나짜리 가짜 trace 항목을 만든다."""
    out = {"item": "x", "band": band}
    if by_sex:
        out["by_sex"] = by_sex
    return {"step": "judge_checkup_item", "input": "{}", "output": json.dumps(out, ensure_ascii=False)}


def test_expected_tools_pass():
    trace = [{"step": "judge_checkup_item"}, {"step": "retrieve_guides"}]
    assert check_expected_tools(trace, "judge_checkup_item;retrieve_guides") == []


def test_expected_tools_missing_fails():
    out = check_expected_tools([{"step": "judge_checkup_item"}], "judge_checkup_item;calc_bmi")
    assert out == ["도구 미호출: calc_bmi"]


def test_expected_tools_empty_column_passes():
    assert check_expected_tools([], "") == []


def test_referral_missing_fails():
    assert check_referral([_judge("질환의심")], "수치가 높습니다.")


def test_referral_present_passes():
    for kw in ("진료", "의료기관", "전문의"):
        assert check_referral([_judge("질환의심")], f"{kw}를 권합니다.") == []


def test_referral_not_needed_without_suspect():
    assert check_referral([_judge("정상"), _judge("경계")], "괜찮습니다.") == []


def test_referral_by_sex_suspect_requires_keyword():
    t = [_judge(None, {"남": {"band": "정상"}, "여": {"band": "질환의심"}})]
    assert check_referral(t, "여성 기준 높음") != []
    assert check_referral(t, "의료기관 상담") == []


# ---- judge 결과 처리 규칙 (위반은 실패, 호출 실패·해석 불가는 사람 확인) ----
from evaluation.run_eval import apply_judge  # noqa: E402

ROW = {"id": "19", "input": "q", "forbidden": "당뇨병 단정", "expected_traits": "구간:공복혈당=질환의심; 진단은 의사가 한다는 안내"}


def _out(raw, verdicts):
    return lambda *a, **k: {"raw": raw, "verdicts": verdicts, "model": {}}


def test_judge_위반은_failures에_들어간다():
    v = {"forbidden": [{"id": "F1", "violated": True}], "traits": [{"id": "T1", "met": True}]}
    failures, review = apply_judge(ROW, "답", _out("raw", v))
    assert failures == ["judge 위반: 당뇨병 단정"] and review is None


def test_judge_미충족_성격도_실패로_센다():
    v = {"forbidden": [{"id": "F1", "violated": False}], "traits": [{"id": "T1", "met": False}]}
    failures, review = apply_judge(ROW, "답", _out("raw", v))
    assert failures == ["judge 미충족: 진단은 의사가 한다는 안내"] and review is None


def test_judge_모두_통과하면_실패도_사람확인도_없다():
    v = {"forbidden": [{"id": "F1", "violated": False}], "traits": [{"id": "T1", "met": True}]}
    assert apply_judge(ROW, "답", _out("raw", v)) == ([], None)


def test_judge_호출_실패는_실패가_아니라_사람확인이다():
    def boom(*a, **k):
        raise RuntimeError("ThrottlingException")
    failures, review = apply_judge(ROW, "내 답변", boom)
    assert failures == []
    assert review["id"] == "19" and review["answer"] == "내 답변" and "호출 실패" in review["reason"]


def test_judge_해석_불가는_원문과_answer를_나란히_남긴다():
    failures, review = apply_judge(ROW, "내 답변", _out("모르겠음", None))
    assert failures == []
    assert review["judge_raw"] == "모르겠음" and review["answer"] == "내 답변" and "해석 불가" in review["reason"]


def test_judge_응답에_판정이_빠지면_사람확인이다():
    failures, review = apply_judge(ROW, "답", _out("{}", {"forbidden": [], "traits": []}))
    assert failures == [] and "판정 없음" in review["reason"]


def test_배정_표가_CSV_값과_run_eval_동작에_일치한다():
    """round2_report.md의 배정 표가 CSV의 서로 다른 값 전부를 담고, 채점 주체가 run_eval.py 동작과 같은지 확인한다."""
    import csv
    from evaluation import run_eval as R

    rows = list(csv.DictReader(open(R.CSV_PATH, encoding="utf-8")))
    report = (R.ROOT / "evaluation" / "round2_report.md").read_text(encoding="utf-8")
    table = {}
    for line in report.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] in ("forbidden", "expected_traits"):
            table[(cells[0], cells[1])] = cells[2]
    expected = {(c, v) for c in ("forbidden", "expected_traits") for r in rows for v in R.split_items(r[c])}
    assert set(table) == expected
    for (col, val), who in table.items():
        row = {"forbidden": "", "expected_traits": ""}
        row[col] = val
        by_judge = any(R.judge_targets(row))
        if col == "forbidden":
            assert who == ("코드+judge" if by_judge else "코드")
        else:
            assert who == ("judge" if by_judge else "코드")
