"""메인 에이전트 진입점: run_query가 항상 answer·contexts·trace 세 키를 돌려준다.

도구 연결(_build_tools)과 모델 순서 전환(_invoke_agent)·run_query 흐름만 여기 두고,
판정·지침 검색·가드레일·응답 문구는 각 도메인 폴더에서 가져온다.
"""
import json
import re

from src.assistant.prompts import (BLOCKED_PREFIX, DISCLAIMER, EMPTY_MESSAGE, FAILURE_MESSAGE, MAX_QUESTION_LEN,
                                   SYSTEM_PROMPT, TOO_LONG_MESSAGE)
from src.assistant.schemas import QueryResponse
from src.assistant.trace import _Recorder
from src.guardrails.input_guard import (BLOCK_MESSAGE, INJECTION_NOTICE, PII_NOTICE, has_injection, has_pii,
                                        input_guard, redact_pii, strip_injection)
from src.guardrails.output_guard import (  # noqa: F401  (테스트·평가가 agent.* 로 쓰는 이름 포함)
    FASTING_ASSUMPTION, FIXED_ANSWER, REFERRAL_NOTICE, UNSUPPORTED_REASON, _BAND_RE,
    ensure_assumptions, ensure_band_consistency, ensure_evidence, ensure_fasting_assumption,
    ensure_referral, ensure_scope_answer, ensure_summary, ensure_unsupported_notice,
    user_stated_fasting)
from src.guides.retrieval import guide_source, retrieve_guides  # noqa: F401
from src.judgement.engine import calc_bmi, judge_checkup_item
from src.judgement.schemas import BmiOutput, JudgeOutput
from src.shared.llm import MODEL_ORDER, _is_throttling, build_chat_model  # noqa: F401


def _build_tools(rec: _Recorder) -> list:
    from langchain_core.tools import tool

    @tool
    def judge_checkup_item_tool(item: str, value: float | str, unit: str = "", sex: str = "", fasting: bool = None) -> str:
        """검진 항목 하나의 수치를 판정한다. sex는 남/여, 모르면 빈 문자열."""
        args = {"item": item, "value": value, "unit": unit or None, "sex": sex or None, "fasting": fasting}
        out = JudgeOutput(**judge_checkup_item(**args)).model_dump_json()
        rec.step("judge_checkup_item", args, out)
        return out

    @tool
    def calc_bmi_tool(height_cm: float, weight_kg: float) -> str:
        """키(cm)와 몸무게(kg)로 체질량지수를 계산한다."""
        out = BmiOutput(**calc_bmi(height_cm, weight_kg)).model_dump_json()
        rec.step("calc_bmi", {"height_cm": height_cm, "weight_kg": weight_kg}, out)
        return out

    @tool
    def retrieve_guides_tool(query: str) -> str:
        """항목별 생활습관 지침을 검색한다."""
        try:
            chunks, status = retrieve_guides(query)
        except Exception as exc:  # 검색이 실패해도 판정 결과는 그대로 보여 준다
            chunks, status = [], f"실패({type(exc).__name__})"
        rec.contexts.extend({"doc_id": c["doc_id"], "text": c["text"]} for c in chunks)
        rec.step("retrieve_guides", query, f"문서 {len(chunks)}건 (검색 상태: {status})")
        body = [f"[{c['doc_id']}]\n{c['text']}" for c in chunks]
        return "\n\n".join(body) or "근거 지침 없음"

    judge_checkup_item_tool.name, calc_bmi_tool.name, retrieve_guides_tool.name = (
        "judge_checkup_item", "calc_bmi", "retrieve_guides")
    return [judge_checkup_item_tool, calc_bmi_tool, retrieve_guides_tool]


_THROTTLED_TIERS: set = set()  # 이 프로세스에서 한도에 걸린 (리전, 모델 ID)는 다음 질문부터 건너뛴다


def _run_agent(question: str, model_id: str, region: str) -> dict:
    """지정한 (리전, 모델) 하나로 LLM 에이전트(ReAct)를 처음부터 실행한다. 실패하면 예외를 던진다."""
    from dotenv import load_dotenv
    from langchain.agents import create_agent

    load_dotenv()
    rec = _Recorder()
    # 기존 서울 리전 global 모델이 일일 토큰 한도에 걸려 MODEL_ORDER의 10단계 순서로 교체 (기술 스택 고정값과 다름)
    model = build_chat_model(model_id, region)  # temperature=0 (src/shared/llm.py)
    agent = create_agent(model, _build_tools(rec), system_prompt=SYSTEM_PROMPT)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    answer, fixed = ensure_scope_answer(result["messages"][-1].text, rec.trace)  # 도구 호출이 없으면 고정 문장
    if fixed:
        return {"answer": answer, "contexts": [], "trace": rec.trace}
    answer = ensure_band_consistency(answer, rec.trace)  # 구간 표기는 코드 판정과 대조한다
    answer = ensure_summary(answer, rec.trace)  # 판정 요약 줄(항목·값·성별별 구간)도 코드가 보장한다
    answer = ensure_assumptions(answer, rec.trace)  # 가정·환산 명시는 코드가 보장한다
    answer = ensure_fasting_assumption(answer, question, rec.trace)  # 사용자가 공복을 말하지 않았으면 공복 가정도 보장한다
    answer = ensure_unsupported_notice(answer, rec.trace)  # 다루지 않는 검사 안내·상담 권유도 코드가 보장한다
    answer = ensure_referral(answer, rec.trace)  # 질환의심 진료 안내(G3)도 코드가 보장한다
    answer, contexts = ensure_evidence(answer, question, rec.contexts, rec.trace)  # 근거 표기도 코드가 보장한다
    return {"answer": answer, "contexts": contexts, "trace": rec.trace}


def _invoke_agent(question: str) -> dict:
    """MODEL_ORDER 순서로 처리하고, 한도(ThrottlingException)가 나면 그 질문을 다음 차수로 처음부터 다시 처리한다.

    한 답변 안에 여러 모델이 섞이지 않으며, 답한 모델·리전은 trace의 llm_model 단계에 남는다.
    한도에 걸린 차수는 기억했다가 다음 질문부터 건너뛴다. 한도가 아닌 오류는 넘기지 않고 그대로 올린다.
    모든 차수가 막히면 마지막 한도 예외를 올린다.
    """
    last_exc: BaseException | None = None
    for tier in MODEL_ORDER:
        if tier in _THROTTLED_TIERS:
            continue
        region, model_id = tier
        try:
            out = _run_agent(question, model_id, region)
        except Exception as exc:
            if not _is_throttling(exc):
                raise
            _THROTTLED_TIERS.add(tier)
            last_exc = exc
            continue
        out["trace"].append({"step": "llm_model", "input": region, "output": model_id})
        return out
    raise last_exc or RuntimeError("ThrottlingException: 10개 모델 차수가 모두 한도에 걸려 있습니다")


def _result(answer: str, contexts: list, trace: list) -> dict:
    """고정 면책 1문장을 코드로 붙여 세 키 모양으로 돌려준다."""
    answer = redact_pii(answer)  # 출력 가드 G4: 어떤 경로의 답이든 개인정보를 가린다
    contexts = [dict(c, text=redact_pii(c["text"])) if isinstance(c, dict) and "text" in c
                else redact_pii(c) if isinstance(c, str) else c for c in contexts]
    return QueryResponse(answer=f"{answer}\n\n{DISCLAIMER}", contexts=contexts, trace=trace).model_dump()


def _guard_step(question: str, guard: dict) -> dict:
    """입력 가드의 감지 사실을 trace 단계로 만든다."""
    found = ", ".join(guard["detected"]) if guard["detected"] else "없음"
    out = f"차단 (감지: {found})" if guard["blocked"] else f"통과 (감지: {found})"
    return {"step": "input_guard", "input": question, "output": out, "detected": guard["detected"],
            "blocked": guard["blocked"]}


def run_query(question) -> dict:
    """질문 하나를 처리한다. 어떤 입력이든 예외 없이 세 키를 돌려준다."""
    if not isinstance(question, str) or not question.strip():
        return _result(EMPTY_MESSAGE, [], [{"step": "error", "input": "", "output": "invalid_question"}])
    if len(question) > MAX_QUESTION_LEN:
        return _result(TOO_LONG_MESSAGE, [], [{"step": "error", "input": "", "output": "too_long"}])
    guard = input_guard(question)
    pii = has_pii(question)
    if pii:
        guard["detected"].append("G4_pii")
    shown = redact_pii(question)  # trace와 에이전트에는 가린 질문만 넘긴다
    inj = has_injection(shown)
    if inj:  # G5: 지시문은 지우고 수치만 판정한다 (차단하지 않는다)
        guard["detected"].append("G5_injection")
        shown = strip_injection(shown) or shown
    if guard["blocked"]:
        msg = f"{BLOCK_MESSAGE}\n{PII_NOTICE}" if pii else BLOCK_MESSAGE
        msg = f"{msg}\n{INJECTION_NOTICE}" if inj else msg
        trace, contexts = [_guard_step(shown, guard)], []
        if re.search(r"\d", shown):  # 같은 질문에 수치가 있으면 그 판정은 정상 수행한다
            try:
                out = _invoke_agent(BLOCKED_PREFIX + shown)
                msg = f"{msg}\n\n{out['answer']}"
                trace, contexts = trace + out.get("trace", []), out.get("contexts", [])
            except Exception as exc:  # 판정이 실패해도 차단 안내는 그대로 낸다
                trace.append({"step": "error", "input": "", "output": type(exc).__name__})
        return _result(msg, contexts, trace)
    try:
        out = _invoke_agent(shown)
        trace = [_guard_step(shown, guard)] + out.get("trace", [])
        answer = f"{out['answer']}\n{PII_NOTICE}" if pii else out["answer"]
        answer = f"{answer}\n{INJECTION_NOTICE}" if inj else answer
        return _result(answer, out.get("contexts", []), trace)
    except Exception as exc:  # Bedrock 실패 등 어떤 오류에도 서버는 멈추지 않는다
        return _result(FAILURE_MESSAGE, [], [_guard_step(shown, guard), {"step": "error", "input": "", "output": type(exc).__name__}])
