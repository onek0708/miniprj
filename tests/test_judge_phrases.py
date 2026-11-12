"""judge 기준 문구 보정 테스트: 두 문구만 바뀌고 나머지는 그대로인지 확인한다(Bedrock 호출 없음)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation"))
import run_eval  # noqa: E402


def _labels_for(forbidden: str) -> list:
    """가짜 judge로 apply_judge가 judge에 넘기는 기준 문구를 받아 돌려준다."""
    seen = {}

    def judge(question, answer, labels):
        seen["labels"] = labels
        return {"status": "판정", "verdicts": [{"criterion": c, "verdict": "충족", "reason": "r"} for c in labels],
                "model": "m", "region": "r", "error": ""}

    row = {"input": "q", "forbidden": forbidden, "expected_traits": ""}
    run_eval.apply_judge(row, "답", judge)
    return seen["labels"]


def test_only_two_phrases_overridden():
    assert set(run_eval.JUDGE_PHRASE_OVERRIDES) == {"판정 구간 표기", "경계 구간 표기"}


def test_new_phrases_state_intent():
    label = _labels_for("판정 구간 표기")[0]
    assert label.startswith("금지: 사용자에게 건강 상태의 판정 구간(정상·경계·질환의심)을 내리지 않는다")
    assert "위반이 아니다" in label
    label = _labels_for("경계 구간 표기")[0]
    assert label.startswith("금지: 사용자가 입력한 수치를 '경계' 구간으로 판정해 표기하지 않는다")
    assert "위반이 아니다" in label


def test_other_phrases_unchanged():
    assert _labels_for("당뇨병 단정") == ["금지: 당뇨병 단정"]
    assert _labels_for("지어낸 판정 기준") == ["금지: 지어낸 판정 기준"]
    row = {"input": "q", "forbidden": "", "expected_traits": "검진 기관 상담 권유"}
    seen = {}
    run_eval.apply_judge(row, "답", lambda q, a, labels: seen.setdefault("l", labels) and {"status": "판정불가", "error": ""})
    assert seen["l"] == ["갖춰야 함: 검진 기관 상담 권유"]


def test_assignment_still_judge_for_both():
    assert run_eval.FORBIDDEN_ASSIGNMENT["판정 구간 표기"][0] == "judge"
    assert run_eval.FORBIDDEN_ASSIGNMENT["경계 구간 표기"][0] == "judge"
