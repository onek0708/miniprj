CLAUDE.md
Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.
2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

"Add validation" → "Write tests for invalid inputs, then make them pass"
"Fix the bug" → "Write a test that reproduces it, then make it pass"
"Refactor X" → "Ensure tests pass before and after"
For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

# 작업 규칙

- 무엇을 만드는지는 SERVICE.md가 기준이다. 애매하면 추측하지 말고 물어본다.
- 스택: Python, LangGraph, Bedrock (anthropic.claude-3-5-sonnet-20241022-v2:0) -> 필요 시 모델은 조정해서 사용하거나 복수의 모델을 상황에 맞춰 변경하여 중단없이 쓸 수 있게 한다.
- 괜찮은 레퍼런스 코드를 깃허브에서 찾아서 레퍼런스로 삼거나 (있을 경우) 현재 ref 폴더 내 코드를 참조한다. 절대 사용자의 허락없이 신규 프레임워크 또는 라이브러리를 들이지 않는다.
- 한 번에 TASKS.md의 작업 하나만 한다.
- 계산, 규칙 판정은 LLM이 아니라 파이썬 코드로 하는 원칙으로 진행한다. 필요시 LLM 판정부분을 덧붙여 추가한다.
- API 키는 .env에서 읽는다.
- Seed 실행은 반드시 Ouroboros(`/ooo run`, `ouroboros_start_execute_seed`)로 한다. Claude가 Seed 내용을 보고 직접 구현·실행하지 않는다. 사용자가 "Seed 실행", "Run Seed"라고 하면 Ouroboros 실행을 뜻한다.
- 사용자가 정한 방법(도구, 실행 방식, 순서)을 Claude가 임의로 바꾸지 않는다. 다른 방법이 낫다고 판단되면 실행 전에 먼저 묻고, 허락을 받은 뒤에만 바꾼다.

# 프로젝트 규칙

## 기술 스택
- Python, LangChain, LangGraph
- 모델은 Amazon Bedrock (ChatBedrockConverse)
- Agent 생성은 langchain.agents 의 create_agent 를 쓴다

## 폴더 구조 (제출 규약 + 도메인별 src/)
제출 규약상 필수 파일 이름(`src/agent.py`, `src/tools.py`, `src/retriever.py`)과 `data/`, `evaluation/`은 유지한다.
`src/` 안은 기술 역할이 아니라 도메인(기능)별 폴더로 나눈다.

```
src/
├── agent.py        메인 에이전트 그래프 (제출 규약 필수). 도구 연결(_build_tools), 모델 순서 전환(_invoke_agent), run_query
├── tools.py        도메인 도구 진입점 (제출 규약 필수). 구현은 judgement/engine.py를 다시 내보내기만 한다
├── retriever.py    RAG 파이프라인 진입점 (제출 규약 필수). 구현은 guides/retrieval.py를 다시 내보내기만 한다
├── app.py          POST /query API 진입점
├── judgement/      판정 도메인: engine.py(판정·BMI 계산 규칙, 코드가 판정), schemas.py(도구 출력 스키마)
├── guides/         지침 검색 도메인: retrieval.py(지침 문서 하이브리드 RAG)
├── guardrails/     가드레일 도메인: input_guard.py(G1·G2 차단, G4 마스킹, G5 지시문 제거), output_guard.py(구간·요약·가정·진료 안내·근거 보장)
├── assistant/      응답 도메인: prompts.py(시스템 프롬프트·고정 문장), schemas.py(응답 스키마), trace.py(trace 기록)
└── shared/         여러 도메인이 함께 쓰는 것만: llm.py(MODEL_ORDER, 한도 오류 판별, 모델 생성)
data/               사용한 문서와 데이터
evaluation/         test_queries.csv 와 평가 리포트
```

### src/ 파일 배치 규칙
- 새 코드는 먼저 어느 도메인(판정·지침 검색·가드레일·응답)에 속하는지 정하고 그 폴더에 둔다. 도메인 폴더에는 실행 로직, 프롬프트·고정 문장, 입출력 스키마를 함께 둔다. `utils`·`models` 같은 기술 역할 폴더는 만들지 않는다.
- 둘 이상의 도메인이 쓰는 LLM 설정·유틸리티만 `src/shared/`에 둔다. 한 도메인만 쓰면 그 도메인에 둔다.
- 도메인끼리는 필요한 쪽에서 가져다 쓴다(예: `guardrails`가 `guides`를 사용). 순환 import를 만들지 않는다.
- `src/agent.py`·`tools.py`·`retriever.py`는 제출 규약 때문에 남긴 진입 파일이다. 로직을 새로 쌓지 말고 도메인 폴더에서 가져오게 한다.
- 모델은 `src/shared/llm.py`의 `build_chat_model`로만 만든다(모듈 최상단에서 만들지 않는다).
- 테스트는 `tests/`에 두고, 모듈 속성을 바꿔치는(monkeypatch) 대상은 그 이름을 실제로 쓰는 모듈이다(예: 근거 검색은 `guardrails.output_guard`, 도구는 `agent`).

## 주고받는 형식 (제출 규약)
- POST /query 로 받고 question 필드를 읽는다
- 답은 answer, contexts, trace 세 키로 돌려준다

## 코드 규칙
- 파일 하나에 한 가지 역할만 둔다
- 함수와 도구에는 한국어 docstring 을 쓴다
- 비밀 값은 .env 에서 읽고 코드에 적지 않는다

## 하지 말 것
- 요청하지 않은 파일을 새로 만들지 않는다
- 기존 파일을 통째로 다시 쓰지 않는다. 바뀐 부분만 고친다