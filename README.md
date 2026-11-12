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

모델은 Bedrock의 10단계 (리전, 모델 ID) 순서입니다(`src/agent.py`의 모듈 상수 목록 하나이며 RAGAS 심판 `evaluation/run_ragas.py`도 같은 목록을 씁니다). 1~5차 Sonnet 4.6: us-west-2 `us.anthropic.claude-sonnet-4-6` → us-west-2 `global.anthropic.claude-sonnet-4-6` → us-east-1 `us.…` → us-east-1 `global.…` → ap-northeast-2 `global.…`. 6~10차 Sonnet 4.5: 같은 리전 순서로 `anthropic.claude-sonnet-4-5-20250929-v1:0`(`us.`/`global.`). 일일 토큰 한도(ThrottlingException)에 걸리면 서비스는 그 질문을, RAGAS는 그 회차를 다음 차수로 처음부터 다시 처리하고, 답한 모델·리전은 trace의 `llm_model` 단계와 결과 파일에 남습니다. Haiku·Nova·gpt-oss는 쓰지 않습니다. AWS 자격 증명은 `.env`에서 읽고 `AWS_DEFAULT_REGION`은 모델 순서와 무관한 기본값입니다. 임베딩은 `amazon.titan-embed-text-v2:0`입니다. 비밀 값은 `.env`에서만 읽고 저장소에 넣지 않습니다.

## 5. RAGAS 평가 결과
| 지표 | 최종 값 (17건) | 개선 전 (13건) |
|---|---|---|
| context_recall | 0.679 | 0.250 |
| context_precision | 0.978 | 0.684 |
| faithfulness | 0.455 | 0.232 |
| answer_relevancy | 0.412 | 0.516 |

- 측정: `python evaluation/run_ragas.py` (ragas 0.4.3). 원본 수치는 `evaluation/results/ragas_round2_improved.json`(최종)과 `ragas_round2.json`(개선 전)에 있습니다.
- 개선 내용:
  - 측정 방식: RAGAS 근거에 코드 판정 결과와 판정 기준(`criteria.json`)을 더했습니다. 서비스 응답의 `contexts`는 그대로입니다.
  - 검색 정확도: 질문 주제와 맞지 않는 지침 조각을 빼는 필터를 넣었습니다(`src/agent.py`).
- 최종 측정에서 제외한 문항은 3건입니다(#9, #11, #18). 다루지 않는 검사, 수치 없음, 약 요청 차단이라 근거가 하나도 없는 문항입니다.
- answer_relevancy는 질문과 답만으로 계산해 이번 수정과 직접 관계가 없습니다. 판정을 하지 않는 답(#12, #17)이 0점으로 들어갔고, 다시 실행하면서 답 문장이 바뀐 문항도 있어 내려갔습니다.
- 심판 모델: 위 4절의 10단계 모델 순서(회차 단위로 넘어가며 결과 파일에 회차별 채점 모델·리전 기록). 당시 측정은 Sonnet 4.6(ap-northeast-2 global)으로 했습니다. 임베딩: `amazon.titan-embed-text-v2:0`.
- 모범 답안: `test_queries.csv`의 `reference` 열입니다. `criteria.json`과 지침 문서를 근거로 작성했습니다.
- 통과 기준 없이 숫자만 기록합니다.
- 계산 규칙(7.4): `answer`와 근거로 계산하고, 근거가 빈 문항은 대상에서 빼고 그 수를 적습니다.
- 자세한 해석과 문항별 비교는 `evaluation/round2_report.md`의 "RAGAS 측정"과 "RAGAS 개선 후 재측정" 절을 봅니다.

## 6. 인-아웃 세트 통과율
고정 20문항(positive 8, negative 4, edge 5, guardrail 3).

| 차수 | 전체 | guardrail |
|---|---|---|
| 1차 | 6/20 (30%) | 0/3 |
| 2차 | 7/20 (35%) → 의존성 설치 후 재측정 8/20 (40%) | 1/3 |
| 2차 재측정 (자격 증명 보완, Sonnet 4.6, #16 수정) | 20/20 (100%) | 3/3 |
| 최종 확인 1·2 (Haiku 예비 모델, `final_eval.json`·`final_eval_retry.json`) | 14/20 (70%), 판정 오류 11건 | 2/3 |
| 최종 확인 3 (10단계 모델 순서, `final_eval_sonnet_order.json`, 커밋 42c6d07) | 20/20 (100%), 판정 오류 0건, judge 도입 전 채점 기준 | 3/3 |
| **LLM-as-Judge 도입 후** (코드 검사+judge, `final_eval_llm_judge.json`, 커밋 3ebd95e) | **17/20 (85%)**, 기준 90% 미달, needs_human_review 0건 | **3/3** |
| **서비스 보완 후** (`final_eval_service_fix.json`, 커밋 e7590e0) | **19/20 (95%)**, 기준 충족 (실패 #4 1건) | **3/3** |

- judge 도입 후 최신 결과(2026-11-12, 커밋 3ebd95e): positive 7/8, negative 2/4, edge 5/5, guardrail 3/3, 전체 17/20(85%)로 전체 기준 90%에 미달했습니다. 실패는 #8(공복 가정 명시 없음), #10(다루지 않는 검사라는 안내 없음), #11(검진 기관 상담 권유 없음)이며 기준·문항·서비스는 고치지 않고 기록만 했습니다. 자세한 내용은 `evaluation/round2_report.md`의 "LLM-as-Judge 도입"을 봅니다.
- judge 도입 전 결과(2026-11-12, 키워드·도구 호출 중심 채점): positive 8/8, negative 4/4, edge 5/5, guardrail 3/3. #1~#17·#19·#20은 `global.anthropic.claude-sonnet-4-6`(us-west-2)가 답했고 #18은 모델 호출이 없었습니다.

- 개선폭: 1차 6/20 → 최종 20/20. 2차 당시에는 #18 하나(채점기 `용량` 오탐 수정)만 통과로 바뀌었고, 나머지는 자격 증명 보완과 모델 변경 후 통과했습니다. 마지막 #16은 프롬프트 정제(성별을 되묻지 않기)와 채점기의 남녀 표기 인정으로 통과했습니다. 측정별 자세한 내용은 `evaluation/round2_report.md`의 "추가 재측정"을 봅니다.
- 목표(전체 90%, guardrail 100%): judge 도입 전 채점에서는 달성했지만 judge 도입 후에는 guardrail 100%만 충족하고 전체는 85%로 미달입니다. 위 20/20은 10단계 모델 순서로 잰 결과이며 실제로는 Sonnet 4.6이 답했습니다.
- 기능 성공 기준 10개와 단위 테스트는 `tests/`에서 확인합니다. 리포트: `evaluation/round1_report.md`, `evaluation/round2_report.md`.

## 7. 트라이앤에러 회고
- 실패한 접근 1 — 모델에게 구간 판정까지 맡기는 방식: 숫자 비교를 틀릴 수 있어 폐기했습니다. 최종은 코드 판정 + 모델 설명으로 분리했고, 출력 가드가 답에 적힌 구간을 `trace`의 판정 결과와 대조해 바로잡습니다.
- 실패한 접근 2 — 금지어 포함 여부로 채점: 올바른 거절 문구 속 '용량'을 위반으로 오탐했습니다(#18). 최종은 숫자+단위 형태의 실제 복용량 안내만 위반으로 봅니다. 답이 아니라 기준이 틀렸던 경우였습니다.
- 실패한 접근 3 — 가드 차단을 모델에 맡기기: 모델 기분에 따라 달라질 수 있어 정규식·키워드 기반 코드 가드로 정했습니다.
- 환경 문제: 첫 측정은 AWS 자격 증명 없음, 다음은 의존성 미설치, 그다음은 일일 토큰 한도로 막혀 코드 개선 효과를 충분히 재지 못했습니다. 다음에는 평가 전에 자격 증명·의존성·한도를 먼저 점검합니다.
- 실패한 접근 4 — 성능이 낮은 모델로 바꾸기: 한도를 피하려고 Haiku 4.5로 바꿨더니 판정 도구를 부르지 않고 성별을 되물어 11/20에 그쳤습니다(초기 시도). 이후 Sonnet 4.6 주 모델 + Haiku 4.5 예비 모델 방식도 시도했으나 최종 평가가 두 번 모두 14/20(guardrail 2/3, 판정 오류 11건)이었습니다. 주 모델이 한도에 걸려 대부분 Haiku가 답했고, 실패 문항(#2, #3, #4, #7, #16, #20)은 판정 도구를 부르지 않아 trace에 판정이 없었습니다. Haiku 예비 모델을 되돌리고 Sonnet 4.6 5개 → Sonnet 4.5 5개의 10단계 모델 순서로 바꿔 20/20을 회복했습니다.
- 남은 한계: 강의 고정 모델(Sonnet 4.5)은 6~10차 대체로만 두었고 최종 평가에서는 쓰이지 않았습니다. RAGAS faithfulness(0.455)와 answer_relevancy(0.412)는 아직 낮고, answer_relevancy는 실행마다 답 문장이 달라져 편차가 큽니다. 검색 설정(k, 키워드·벡터 비중)은 아직 RAGAS로 비교해 고르지 않았습니다.

## 7-1. 2차 개선 1단계: 검색 설정 비교와 모델 설정 변경
- 고른 검색 설정: k=3, 같은 비중 RRF 1/(60+순위) 유지(코드 변경 없음). 수치 목표는 두지 않았다.
- 비교 결과 요약(context_recall·context_precision 평균, 11문항, 조합마다 2회, Sonnet 4.6 채점): k=2 0.5303, k=3(기준선) 0.5183, k=5 0.5450, 키워드 0.7:벡터 0.3 0.5057. 키워드 0.3:벡터 0.7은 2회차를 예비 모델이 채점해 직접 비교가 불가해 채택하지 않았다. k=5와의 차이(0.0267)는 2회 편차(0.0289) 안이라 기준선을 유지했다. 자세한 표와 한계는 `evaluation/round2_report.md`.
- 측정 방법: 기준 설정으로 서비스를 한 번만 돌려 저장한 검색 질문문으로 검색 함수만 다시 실행해 검색 지표 두 개만 쟀다(답변 재생성 제거, 호출량 감소).
- 모델 설정 변경(이력): 이 단계에서는 `us-west-2` 주 모델 `us.anthropic.claude-sonnet-4-6` + Haiku 4.5 예비 모델로 바꿨다(서울 리전 global 모델과 us-east-1이 일일 토큰 한도에 걸려 측정이 중단됐기 때문). 이 Haiku 예비 모델 설정은 최종 확인에서 14/20이 나와 되돌렸고, 현재는 4절의 10단계 모델 순서가 서비스와 RAGAS 심판에 적용된다. 서비스는 질문 단위, RAGAS는 회차 단위로 넘어간다. 아래 측정 결과(k=3 유지, 벡터 우선 회차의 채점 모델 섞임)는 당시 설정 기준 기록이며 다시 측정하지 않았다.

## 8. 핵심 코드 위치
- `src/agent.py`: `run_query`(진입·면책), 출력 가드(`ensure_band_consistency`, `ensure_evidence`, `ensure_referral`, `ensure_assumptions`), `_build_tools`
- `src/tools.py`: `judge_checkup_item`, `judge_blood_pressure`, `calc_bmi`
- `src/retriever.py`: `hybrid_search`, `retrieve_guides`
- `src/guards.py`: `input_guard`, `redact_pii`, `strip_injection`
- `src/app.py`: `POST /query`
- `data/criteria.json`: 판정 구간과 출처(기관명·기준일), `data/guides/*.md`: 지침 문서
