# 건강검진 수치 해석 어시스턴트

> 교육용 프로젝트입니다. 검진 수치와 사용자 정보는 모두 더미 데이터이며, 진단·약 처방을 하지 않습니다.

## 1. 무엇을 푸나
건강검진 수치를 넣으면 항목별 판정 구간(정상 / 경계 / 질환의심)과 생활습관 지침을 근거(기관명·기준일, 지침 문서)와 함께 답합니다.

## 2. 활용한 패턴 (Day 1~7)
- Day 1: 프롬프트·구조화 출력 — 판정·BMI 결과를 Pydantic 모델(`JudgeOutput`, `BmiOutput`, `QueryResponse`)로 고정하고 응답을 `answer`·`contexts`·`trace` 세 키로 맞춥니다.
- Day 2: RAG (하이브리드 검색) — 키워드 검색과 Chroma 벡터 검색(Titan 임베딩)을 합쳐 `data/guides/*.md`에서 지침을 찾고, 결과를 `contexts`(`파일명#헤더`)로 돌려줍니다. (`src/retriever.py`)
- Day 3: ReAct — `create_agent`가 질문에 따라 판정·계산·검색 도구를 골라 호출합니다.
- Day 4: 도구 다중 — 한 질문에 `judge_checkup_item`, `judge_blood_pressure`, `calc_bmi`, 지침 검색을 함께 씁니다.
- Day 5: 가드레일 — 입력 가드(진단 확정·약 요청 차단, 인젝션 제거, 개인정보 마스킹)와 출력 가드(구간 표기 대조, 진료 안내·출처·가정 보충)를 코드로 둡니다. (`src/guards.py`, `src/agent.py`)
- Day 5: 미들웨어 — 개인정보 마스킹, 모델 호출 실패 시 고정 안내 문구로 응답하고 서버는 멈추지 않습니다.
- Day 7: Observability — 응답 `trace`에 단계별(가드, 도구 호출, 검색) 기록을 남깁니다.
- Day 7: 평가 — 질문 20건 인-아웃 세트와 `evaluation/run_eval.py`로 카테고리별·전체 통과율을 잽니다.

쓰지 않은 패턴 (이유):
- HITL: 되돌릴 수 없는 작업이 없어 쓰지 않았습니다.
- Multi-Agent Supervisor: 에이전트 하나로 충분한 규모라 쓰지 않았습니다.
- Plan-Execute·장기 메모리: 한 번 묻고 한 번 답하는 서비스라 쓰지 않았습니다.
- MCP 서버 연동(선택)도 넣지 않았습니다.

## 3. 아키텍처
```
질문 → 입력 가드(길이·형식, 개인정보 마스킹, 인젝션 제거, 약·진단 확정 차단)
     → 에이전트(모델이 항목·수치 추출 → 도구 호출)
         ├─ judge_checkup_item / judge_blood_pressure / calc_bmi (코드 판정, data/criteria.json)
         └─ 지침 검색 (키워드 + Chroma 하이브리드, data/guides/*.md)
     → 출력 가드(진단 단정·약 추천 차단, 구간 표기 대조, 질환의심 진료 안내, 출처·가정 보충)
     → 고정 면책 1문장을 코드가 붙여 {answer, contexts, trace} 응답
```

| 일 | 담당 |
|---|---|
| 구간 판정, 판정 보류 | 코드 (`judge_checkup_item`) — 모델은 숫자 비교를 틀릴 수 있기 때문 |
| 체질량지수 계산 | 코드 (`calc_bmi`) |
| 질문에서 항목·수치 읽기 | 모델(추출) + 코드(검증) |
| 지침 검색과 요약 | RAG + 모델 |
| 고정 면책 문장 | 코드 (`run_query`) |
| 개인정보 마스킹, 인젝션 제거, 약·진단 확정 요청 감지 | 코드 (입력 가드) |
| 금지 표현 차단, 구간 표기 대조, 진료 권고 보충 | 코드 (출력 가드) |

지침 검색(Chroma)만 실패하면 코드 판정 결과와 기준 출처는 그대로 보여 주고 지침 자리에 "근거 지침 없음"을 안내합니다.

## 4. 실행 방법
```bash
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION(us-east-1) 입력
uvicorn src.app:app --port 8000
```
요청 예시:
```bash
curl -X POST http://localhost:8000/query -H "Content-Type: application/json" \
  -d '{"question": "공복혈당이 108이 나왔어요"}'
```
테스트: `python -m pytest -q tests`, 평가: `python evaluation/run_eval.py --out evaluation/results/round2.json`

모델은 Bedrock `global.anthropic.claude-sonnet-4-6`(리전 `ap-northeast-2`)입니다. 강의 고정값 `us.anthropic.claude-sonnet-4-5-20250929-v1:0`(`us-east-1`)이 일일 토큰 한도에 걸려 바꿨습니다(`src/agent.py`의 `_invoke_agent`에서 바꿀 수 있음). 임베딩은 `amazon.titan-embed-text-v2:0`입니다. 비밀 값은 `.env`에서만 읽고 저장소에 넣지 않습니다.

## 5. RAGAS 평가 결과
| 지표 | 값 | 계산 대상 문항 수 |
|---|---|---|
| context_recall | 0.250 | 13 |
| context_precision | 0.684 | 13 |
| faithfulness | 0.232 | 13 |
| answer_relevancy | 0.516 | 13 |

- 측정: `python evaluation/run_ragas.py` (ragas 0.4.3), 원본 수치는 `evaluation/results/ragas_round2.json`에 있습니다.
- 심판 모델: `global.anthropic.claude-sonnet-4-6`(ap-northeast-2). 임베딩: `amazon.titan-embed-text-v2:0`.
- 모범 답안: `test_queries.csv`의 `reference` 열입니다. `criteria.json`과 지침 문서를 근거로 작성했습니다.
- 통과 기준 없이 숫자만 기록합니다.
- 계산 규칙(7.4): `answer`와 `contexts`로 계산하고, `contexts`가 빈 문항은 대상에서 빼고 그 수를 적습니다. 이번에는 20문항 중 7건을 뺐습니다(#2, #8, #11, #12, #14, #17, #18).
- faithfulness·context_recall이 낮은 이유: 판정 구간은 코드 판정 결과로 답에 들어가는데, RAGAS `contexts`에는 지침 문서 조각만 들어가기 때문입니다. 자세한 해석은 `evaluation/round2_report.md`의 "RAGAS 측정" 절을 봅니다.

## 6. 인-아웃 세트 통과율
고정 20문항(positive 8, negative 4, edge 5, guardrail 3).

| 차수 | 전체 | guardrail |
|---|---|---|
| 1차 | 6/20 (30%) | 0/3 |
| 2차 | 7/20 (35%) → 의존성 설치 후 재측정 8/20 (40%) | 1/3 |
| 2차 재측정 (자격 증명 보완, Sonnet 4.6, #16 수정) | **20/20 (100%)** | **3/3** |

- 개선폭: 1차 6/20 → 최종 20/20. 2차 당시에는 #18 하나(채점기 `용량` 오탐 수정)만 통과로 바뀌었고, 나머지는 자격 증명 보완과 모델 변경 후 통과했습니다. 마지막 #16은 프롬프트 정제(성별을 되묻지 않기)와 채점기의 남녀 표기 인정으로 통과했습니다. 측정별 자세한 내용은 `evaluation/round2_report.md`의 "추가 재측정"을 봅니다.
- 목표(전체 90%, guardrail 100%)는 재측정에서 달성했습니다. 단, 강의 고정 모델(Sonnet 4.5)이 아니라 Sonnet 4.6으로 잰 결과입니다.
- 기능 성공 기준 10개와 단위 테스트는 `tests/`에서 확인합니다. 리포트: `evaluation/round1_report.md`, `evaluation/round2_report.md`.

## 7. 트라이앤에러 회고
- 실패한 접근 1 — 모델에게 구간 판정까지 맡기는 방식: 숫자 비교를 틀릴 수 있어 폐기했습니다. 최종은 코드 판정 + 모델 설명으로 분리했고, 출력 가드가 답에 적힌 구간을 `trace`의 판정 결과와 대조해 바로잡습니다.
- 실패한 접근 2 — 금지어 포함 여부로 채점: 올바른 거절 문구 속 '용량'을 위반으로 오탐했습니다(#18). 최종은 숫자+단위 형태의 실제 복용량 안내만 위반으로 봅니다. 답이 아니라 기준이 틀렸던 경우였습니다.
- 실패한 접근 3 — 가드 차단을 모델에 맡기기: 모델 기분에 따라 달라질 수 있어 정규식·키워드 기반 코드 가드로 정했습니다.
- 환경 문제: 첫 측정은 AWS 자격 증명 없음, 다음은 의존성 미설치, 그다음은 일일 토큰 한도로 막혀 코드 개선 효과를 충분히 재지 못했습니다. 다음에는 평가 전에 자격 증명·의존성·한도를 먼저 점검합니다.
- 실패한 접근 4 — 성능이 낮은 모델로 바꾸기: 한도를 피하려고 Haiku 4.5로 바꿨더니 판정 도구를 부르지 않고 성별을 되물어 11/20에 그쳤습니다. Sonnet 계열의 다른 추론 프로필·리전(Sonnet 4.6, 서울)으로 바꿔 해결했습니다.
- 남은 한계: 강의 고정 모델(Sonnet 4.5)로는 20문항을 끝까지 재지 못했습니다. RAGAS는 측정했지만, 판정 근거가 `contexts`에 들어가지 않아 faithfulness·context_recall이 낮게 나옵니다.

## 8. 핵심 코드 위치
- `src/agent.py`: `run_query`(진입·면책), 출력 가드(`ensure_band_consistency`, `ensure_evidence`, `ensure_referral`, `ensure_assumptions`), `_build_tools`
- `src/tools.py`: `judge_checkup_item`, `judge_blood_pressure`, `calc_bmi`
- `src/retriever.py`: `hybrid_search`, `retrieve_guides`
- `src/guards.py`: `input_guard`, `redact_pii`, `strip_injection`
- `src/app.py`: `POST /query`
- `data/criteria.json`: 판정 구간과 출처(기관명·기준일), `data/guides/*.md`: 지침 문서
