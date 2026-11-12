# 인수인계: miniprj3 RAG 품질 2차 개선 (2026-11-12 기준)

이전 세션의 컨텍스트가 가득 차서 새 세션으로 넘깁니다. 이 문서만 읽고 이어서 작업할 수 있게 정리했습니다.

---

## 0. 새 세션이 가장 먼저 할 일

1. **실행 중인 Ouroboros 작업 상태를 확인합니다.**
   - 작업 ID `job_c224f1e9c627`, 세션 `orch_f9702d939609`
   - `ouroboros_job_status`로 상태를 보고, 끝났으면 `ouroboros_job_result`로 결과를 가져옵니다.
2. **"완료" 표시만 믿지 말고 실제 산출물을 엽니다.** 이전 실행은 Bedrock 한도로 측정을 거의 못 했는데도 "13/13 완료"로 표시됐습니다. 아래를 직접 확인합니다.
   - 작업 폴더의 `evaluation/round2_report.md`: 단계별 표에 실제 숫자가 있는지
   - `evaluation/results/`: 측정 결과 파일이 조합·회차별로 다 있는지, `evaluated`가 0건이 아닌지
   - `git log`: 단계마다 커밋됐는지
3. **결과를 사용자에게 한국어로 보고합니다.** 측정이 안 된 부분, 한도로 멈춘 부분을 숨기지 않습니다.

---

## 1. 반드시 지킬 규칙 (사용자가 강하게 요구함)

- **Seed 실행은 반드시 Ouroboros로 합니다.** (`ooo run` = `ouroboros_start_execute_seed`) Claude가 Seed 내용을 보고 직접 구현·실행하면 안 됩니다. 이전 세션에서 두 번 직접 실행했다가 사용자에게 크게 지적받았고, `CLAUDE.md` 작업 규칙과 메모리에 기록돼 있습니다.
- **사용자가 정한 방법(도구, 실행 방식, 순서)을 임의로 바꾸지 않습니다.** 다른 방법이 낫다고 판단되면 실행 전에 묻고 허락받은 뒤에만 바꿉니다.
- **커밋·푸시는 사용자가 명시적으로 요청할 때만 합니다.** `.env`와 키는 절대 커밋하지 않습니다.
- **답변은 한국어, 쉬운 말로 합니다.** 사용자가 기술 용어가 많은 질문을 이해하기 어렵다고 한 적이 있습니다.

---

## 2. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 경로 | `C:\Users\Admin\Desktop\ws\miniprj3` (원격 `onek0708/miniprj3`, 브랜치 `main`) |
| 무엇 | 건강검진 수치를 넣으면 판정 구간(정상/경계/질환의심)과 생활습관 지침을 근거와 함께 답하는 어시스턴트. 삼성SDS AX 교육 Day 8~10 미니 프로젝트 |
| 기준 문서 | `GUIDE.md`(PRD, 제출 구조·평가 계획), `SERVICE.md`(서비스 스펙, 기능 성공 기준 10개) |
| 핵심 원칙 | 판정·계산은 파이썬 코드, 모델은 설명과 지침 검색만. 진단·약 처방 안 함 |
| API | `POST /query` → `answer`, `contexts`, `trace` 세 키 |
| 평가 | `evaluation/test_queries.csv` 20문항(`run_eval.py`), RAGAS 4지표(`run_ragas.py`) |

### main 브랜치 현재 상태 (커밋 c896640)
- 20문항 평가 **20/20**, guardrail 3/3 (Sonnet 4.6 서울 리전 기준)
- 단위 테스트 143개 통과
- RAGAS(개선 후, 17건 계산): context_recall 0.679, context_precision 0.978, faithfulness 0.455, answer_relevancy 0.412
- 지침 주제 필터(관련 없는 지침 조각 제외)가 들어가 있음
- 서비스 모델: `global.anthropic.claude-sonnet-4-6` (ap-northeast-2). 강의 고정값(Sonnet 4.5, us-east-1)과 다르며 README에 기록됨
- 작업 폴더에 **커밋 안 된 `CLAUDE.md` 수정**이 있음 (Ouroboros 규칙 2줄 추가). 사용자 요청 없이는 커밋하지 않음
- `HANDOFF.md`(이 문서)도 커밋 안 됨

---

## 3. 지금 진행 중인 작업: RAG 품질 2차 개선

### 목표
① 검색 설정(k, 키워드·벡터 RRF 비중) 선택 → ② answer_relevancy 실행 간 편차 축소 → ③ faithfulness 개선. RAGAS 2회 반복 측정과 정해진 채택 규칙으로 판정하고, 결과를 `round2_report.md`와 README에 기록. 20/20과 단위 테스트, API 계약은 유지.

### 사용 중인 Seed: `seed_29cf45b36e32`
- 파일: `C:\Users\Admin\.ouroboros\seeds\seed_29cf45b36e32.yaml` (제약 42개, 수용 기준 15개)
- 인터뷰 `interview_20261112_004636`(모호성 0.138)에서 정한 규칙 + GUIDE/SERVICE 대조로 찾은 누락 항목 13개 + 모델 변경 항목
- 주요 규칙
  - 검색 설정 5조합: 같은 비중에서 k=2·3·5 → 고른 k에서 키워드 0.7:벡터 0.3, 0.3:0.7
  - 조합마다 RAGAS 2회 평균. 차이가 2회 편차보다 작으면 기존(k=3, 같은 비중) 유지
  - 2단계 방법: (1) 판정 못 하는 질문도 "확인된 사실 + 다음 행동"으로 답하게 프롬프트 수정, (2) temperature=0
  - 3단계 방법: (1) 근거에 있는 내용만 쓰게 프롬프트 강화, (2) 근거 없는 일반 조언 금지
  - 채택 전마다 pytest와 20문항 평가. 깨지면 되돌리고 기록
  - `test_queries.csv`, `criteria.json`은 고치지 않음
  - Bedrock 한도에 걸리면 그 시점까지 기록하고 멈춤. 모델을 임의로 다시 바꾸지 않음
- **모델 변경(이 Seed에서 새로 넣음):** 서비스 `us.anthropic.claude-sonnet-4-6` (us-west-2), RAGAS 심판 `us.anthropic.claude-sonnet-4-6` (us-east-1). 서울 리전이 Bedrock 일일 한도에 걸렸기 때문
- **LLM-as-Judge는 이번 범위 밖:** `run_eval.py` 채점 방식은 바꾸지 않고, 미구현 사실만 리포트 한계에 기록

### 실행 이력 (오늘)

| 작업 ID | Seed | 결과 |
|---|---|---|
| `job_539c3141bc92` | seed_37e363c5b5c9 | Claude 사용 한도로 실패, 0/8 |
| `job_44c0937c589c` | seed_37e363c5b5c9 | 누락 항목 추가하려고 취소 |
| `job_3eadde904710` | seed_bb96308c545c | "13/13 완료" 표시였으나 실제로는 **Bedrock 일일 한도로 측정 거의 안 됨**. 자동 평가 0/13(pytest 실행 방식 문제), Ralph 루프 중단 |
| `job_751f6e97ec38` | seed_29cf45b36e32 | Claude 사용 한도로 실패, 4/15 |
| **`job_c224f1e9c627`** | **seed_29cf45b36e32** | **실행 중** (13:4x 시작, 작업 폴더 `orch_f9702d939609`, `.env` 복사함) |

- 진행 화면: http://localhost:49258/?run=exec_36401484d5b6
- 관찰용 보조 AI는 붙이지 않음 (Claude 사용량 절약). 상태는 요청받을 때 조회

---

## 4. 작업 폴더(worktree) 정리

위치: `C:\Users\Admin\.ouroboros\worktrees\miniprj3\`

| 폴더 | 내용 | 처리 |
|---|---|---|
| `orch_5b4c40f5e518` | 첫 Seed로 만든 원래 작업 브랜치. **RAGAS가 설치된 `.venv`가 있음.** 이전 세션이 직접 만든 실험 코드(검색 설정 조정, `run_experiments.py`, `compare_experiments.py`)가 커밋 안 된 채 남아 있음 | 사용자가 "남겨 두라"고 함. 지우지 말 것 |
| `orch_6652c08e9413` | 실패한 실행 | 정리 대상 후보 |
| `orch_6aa4e7fd0b21` | 취소한 실행 (커밋 안 된 변경 있음) | 정리 대상 후보 |
| `orch_5546a6e1993f` | 한도로 측정 못 한 실행. 커밋 d4e1a13(가중치 인자, 측정 스크립트)과 Ralph 체크포인트 있음 | 참고용 |
| `orch_f1b08f2a6597` | Claude 한도로 실패. 모델 변경·`pytest.ini` 등이 커밋 안 된 채 있음 | 참고용 |
| `orch_f9702d939609` | **지금 실행 중** | 건드리지 말 것 |

새 Ouroboros 실행을 시작하면 새 작업 폴더가 생기는데 `.env`가 없습니다. 실행 직후 `C:\Users\Admin\Desktop\ws\miniprj3\.env`를 복사하고 `git check-ignore -q .env`로 추적 제외를 확인합니다. (사용자 승인 받은 절차)

---

## 5. 사용량 한도 문제 (반복 발생)

| 한도 | 원인 | 확인 방법 |
|---|---|---|
| **Claude 개인 사용 한도** (조직 ucanlabs, 5시간 단위) | Ouroboros 작업용 AI가 같은 Claude 로그인을 씀. 품질 우선 모드, 실패 후 자동 평가·Ralph 연쇄, 처음부터 재실행 반복, 긴 대화 | `claude -p "OK라고만 답해" --model sonnet < /dev/null` |
| **Bedrock 일일 토큰 한도** (AWS 계정) | RAGAS 측정이 회당 수백 번 호출. 이 Seed는 20회 이상 측정 | 이전 세션 스크래치 `probe4.py`와 같은 방식으로 모델별 3회 호출 |

### 사용자에게 제안했지만 아직 결정 안 된 것
- **Seed를 단계별로 나누기** (① 검색 설정 / ② answer_relevancy / ③ faithfulness 각각 Seed). 실행이 짧아지고 끝난 단계가 남음
- **실패 시 Ralph 자동 시작 끄기** (`auto_evolve: false`)
- 지금 실행 결과를 본 뒤 정하기로 함

---

## 6. 사용자가 맡긴 채 멈춘 일

- **3개 저장소 커밋·푸시:** 사용자가 "3개 레포지토리 커밋하고 푸쉬해줘"라고 했다가 중단함. 어떤 3개인지 확정하지 못했음. `ws/` 아래 git 저장소는 다섯 개:
  - `miniprj` (PRD.md 수정), `miniprj2` (변경 없음), `miniprj3` (CLAUDE.md 수정, main이 origin보다 앞서 있었음), `sds-ax-practice` (PDF 삭제 1건, checkpoint zip 2개), `sds-ax-training` (WORK_ORDER.md 수정, 새 md 1개)
  - **재개 전에 어떤 3개인지, zip·PDF 삭제를 포함할지 사용자에게 확인할 것**
- **SERVICE.md의 모델 표기:** 지금은 서울 리전 Sonnet 4.6으로 적혀 있음. 이번 실행이 `us.` 모델로 확정되면 맞춰야 함 (Seed는 SERVICE.md를 고치지 말라고 함 → 실행 후 사용자 확인 받고 수정)
- **LLM-as-Judge 구현:** 별도 Seed로 하기로 함. 권장안: 기존 코드 채점은 유지하고 judge 결과를 별도 열로 기록, 문장 성격 항목만 judge가 봄, `expected_tools` trace 검사도 추가. 지금 실행이 끝난 뒤 진행
- **공통 규칙을 SERVICE.md에 "공통 작업 규칙" 절로 모으기:** 제안만 함. 다음 Seed마다 같은 제약을 다시 넣지 않으려는 목적

---

## 7. Ouroboros 사용 요령 (이전 세션에서 확인한 것)

- **Seed는 서로 이어지지 않음.** 새 Seed를 만들 때 이전 Seed의 제약을 다시 넣어야 함
- **새 인터뷰는 이전 인터뷰를 모름.** 연장선이면 이전 결정을 시작 문맥에 넣어야 함. 끝난 인터뷰는 다시 열 수 없음
- **인터뷰는 SERVICE.md를 자동으로 읽지 않음.** 문서 내용은 Claude가 읽어서 시작 문맥에 넣어 줘야 함
- **`ooo seed`를 인터뷰 없이 쓰면** (`generate_seed`에 `session_context`) 넘긴 문장이 그대로 들어감. 수용 기준은 문자열 목록으로 넘길 것 (객체로 넘기면 깨짐)
- **Seed 파일이 디스크에 자동 저장되지 않는 경우가 있음.** 실행 전에 `~/.ouroboros/seeds/`에 파일이 있는지 확인. 없으면 YAML로 저장해서 `seed_path`로 넘김
- **실패한 세션은 이어서 실행 불가** ("already failed and cannot be resumed") → 같은 Seed로 새로 실행
- **인터뷰 질문마다 보조 조사 AI 6개를 띄우라는 요청이 옴.** 사용량 때문에 띄우지 않고 질문을 바로 사용자에게 쉬운 말로 물어봄
- **자동 평가 1단계는 작업 폴더에서 `pytest`를 그대로 실행함.** `python -m pytest`가 아니라서 테스트 수집에 실패한 적 있음 → 이번 Seed에 "`pytest`만으로 통과" 제약을 넣음

### Seed 파일 목록 (`C:\Users\Admin\.ouroboros\seeds\`)
- `seed_29cf45b36e32` — 지금 실행 중
- `seed_bb96308c545c` — 이전 버전(모델 변경 전)
- `seed_333ddc048ab9` — 현재 코드를 처음 만든 Seed
- `seed_8cd8a900508a` — 다른 프로젝트(`miniprj`) 것, 손대지 않음
- `_archive/` — 쓰지 않는 Seed 2개 (`seed_37e363c5b5c9`, `seed_e588b0766919`)

---

## 8. 참고 파일

- 메모리: `C:\Users\Admin\.claude\projects\C--Users-Admin-Desktop-ws-miniprj3\memory\seed-runs-via-ouroboros-only.md`
- 이전 세션 대화 기록: `C:\Users\Admin\.claude\projects\C--Users-Admin-Desktop-ws-miniprj3\afbdea2d-4806-4964-9384-f93af047ffbd.jsonl`
- Ouroboros 내부 기록(SQLite): `C:\Users\Admin\.ouroboros\data\ouroboros.db` (실패 원인은 `events` 테이블에서 실행 ID로 검색)
