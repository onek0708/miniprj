"""입력 가드(G1·G2 차단 감지, G4 개인정보 마스킹, G5 지시문 제거). 출력 가드는 output_guard.py."""
import re

# 약·용량·건강기능식품 요청 (G2)
_DRUG = re.compile(r"(약\s*(을|좀)?\s*(추천|처방|먹|복용)|[가-힣]{1,4}약\s*(을|이|은|좀)?\s*(뭐|무엇|무슨|어떤|추천|처방|먹|복용|드)|(무슨|어떤|무슨\s*종류의)\s*약|처방|복용량|용량|영양제|건강기능식품|보충제|\d+\s*(mg|밀리그램))")
# 진단 확정 요청 (G1)
_DIAG = re.compile(r"(무슨\s*병|병이\s*맞|(당뇨|고혈압|지방간|간염|고지혈증|이상지질혈증)\S*\s*(맞|확정|진단)|진단\s*(해|내려|확정))")

BLOCK_MESSAGE = "약·용량·건강기능식품 추천이나 진단 확정은 안내할 수 없습니다. 정확한 판단과 치료는 의료기관에서 진료를 받아 상담해 주세요."


def input_guard(question: str) -> dict:
    """질문을 검사해 차단 여부와 감지 사실을 돌려준다."""
    detected = []
    if _DRUG.search(question):
        detected.append("G2_drug")
    if _DIAG.search(question):
        detected.append("G1_diagnosis")
    return {"blocked": bool(detected), "detected": detected}


# 개인정보 (G4): 주민등록번호, 전화번호, 이메일
_RRN = re.compile(r"(?<!\d)\d{6}\s*[-‐-―~.\s]\s*[1-8]\d{6}(?!\d)|(?<!\d)\d{6}[1-4]\d{6}(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+82[-.\s]?)?0\d{1,2}[-.\s)]*\d{3,4}[-.\s]*\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PII_MASK = "[개인정보 삭제]"
PII_NOTICE = "입력하신 주민등록번호·전화번호 같은 개인정보는 답변에 사용하거나 반복하지 않습니다."


def redact_pii(text: str) -> str:
    """주민등록번호·전화번호·이메일을 가린다. 두 번 돌려도 결과가 같다."""
    return _PHONE.sub(PII_MASK, _RRN.sub(PII_MASK, _EMAIL.sub(PII_MASK, text)))


def has_pii(text: str) -> bool:
    """텍스트에 주민등록번호·전화번호·이메일이 있는지 확인한다."""
    return redact_pii(text) != text


# 지시문 주입 (G5): 차단하지 않고 지시 부분만 지운 뒤 수치는 정상 판정한다
_INJECT = re.compile(
    r"((이전|위|앞|기존|모든|지금까지의?)\s*(의\s*)?(지시|지침|명령|프롬프트|규칙|설정)\w*\s*(을|를|은|는)?\s*(모두\s*|전부\s*)?"
    r"(무시|잊어|잊고|따르지\s*(말|마))\w*\s*(하고|해서|하세요|해|해라|해줘)?[,\s]*"
    r"((무조건|항상|그냥|일단)?\s*(전부\s*)?(정상|괜찮다|문제\s*없다)\w*\s*(이?라고|고)?\s*(답|말|대답|출력|판정)\w*)?"
    r"|ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions?|prompts?)[^.!?\n]*"
    r"|시스템\s*프롬프트\s*(를|을)?\s*(공개|출력|보여)\w*"
    r"|(무조건|항상)\s*(정상|괜찮다)\w*\s*(이?라고)?\s*(답|말|대답)\w*"
    # 아래는 Day05 방식: 단어 하나가 아니라 "덮어쓰려는 동작"과 "현재 지시라는 대상"이 함께 나올 때만 잡는다
    r"|(지시|명령|프롬프트|규칙|대화\s*내용|대화)\S*\s*(은|는|을|를)?\s*(모두\s*|전부\s*|다\s*)?(무시|잊|됐고|따르지\s*(말|마))\w*"
    r"|(ignore|forget|disregard|override)\s+(all\s+|the\s+|your\s+|any\s+)?(previous\s+|prior\s+|above\s+|earlier\s+)?(instructions?|prompts?|rules?)"
    r"|(지금부터|이제부터)\s*(너|당신)(의\s*역할)?\s*(은|는|이)\s*[^.!?\n]{0,20}?(야|이다|입니다|이야|다)(?=[\s.!?,]|$)"
    r"|you\s+are\s+now\s+[^.!?]*"
    r"|(관리자|개발자|디버그|점검|DAN)\s*모드\S*\s*(로\s*)?(전환|진입|들어가|바꿔)\w*"
    r"|새로운\s*역할\S*\s*(부여\s*받|맡)(아라|아|으세요|아\s*줘|어라)(?=[\s.!?,]|$)"
    r"|(시스템|system)\s*(프롬프트|메시지|message|prompt|지침|instructions?)[^.!?\n]{0,15}?(알려|출력|보여|공개|말해|reveal|show|print|tell)\w*"
    r"|#{2,}\s*(new\s+)?instructions?\s*#*"
    r"|reveal\s+(your|the)\s+(system\s+)?prompt"
    r"|그대로\s*따라\s*해[^.!?\n]*"
    r"|(비밀번호|API\s*키|토큰|token|password|secret)\S*\s*[^.!?\n]{0,6}?(출력|보여|알려|공개)\w*"
    r"|(DB|데이터베이스|database)\S*\s*(전부\s*|모두\s*)?(삭제|지우|drop|delete)\w*(\s*\S*\s*(명령|쿼리)\S*)?(\s*실행\w*)?"
    # 강의 실습(day5_practice) 공격 유형: 규칙 없는 AI, 역할 문구, system:/<admin> 구분자, 숨겨진 지시 빼내기, 새 명령, 테이블 삭제
    r"|규칙\s*(이|가)\s*없는\s*(AI|인공지능|모드)\S*"
    r"|새로운\s*역할(로|을)\s*(답|응답|행동)\w*"
    r"|(system|admin|root)\s*:\s*[^.!?\n]*"
    r"|<(system|admin|root)>[^<]*</(system|admin|root)>|</?(system|admin|root)>"
    r"|(첫\s*(번째\s*)?지시문|숨겨진\s*(지시|프롬프트))\S*\s*(을|를)?\s*(그대로\s*)?(공개|출력|알려)\w*"
    r"|새로운\s*(명령|지시)\S*\s*[:：][^.!?\n]*"
    r"|(테이블|table)\S*\s*(을|를)?\s*(전부\s*|모두\s*)?(삭제|지우|drop|delete)\w*"
    r"|(관리자|개발자|디버그|점검|DAN)\s*모드\S*\s*(활성화|켜)\w*"
    # 추가 공격 유형: 서버 종료 명령, 권한 상승(승인 사칭·자격증명 요구), 역할극, 프롬프트 요약·규칙 목록 빼내기, 맥락 초기화
    r"|(프로덕션|운영\s*서버|production|prod)\S*\s*(서버\S*\s*)?(전부\s*|모두\s*|전체\s*)?(즉시\s*)?(종료|중단|셧다운|shutdown|삭제|kill)\w*[^.!?]*"
    r"|(보안팀|관리자|운영팀|IT팀|개발팀)\S*\s*(의\s*)?(승인|허가|허락)\S*\s*(을|를)?\s*(받았|얻었)\w*"
    r"|(자격\s*증명|credentials?|크리덴셜)\S*\s*(을|를)?\s*(출력|보여|알려|공개)\w*"
    r"|역할\s*극\S*[^.!?]*"
    r"|(너는|당신은|넌)\s*(이제\s*|지금부터\s*)?[^.!?]{0,25}?(사서|해커|비서)(야|이야|이다|입니다|처럼)\w*"
    r"|(프롬프트|지시문)\S*\s*(을|를)?\s*(요약|번역|다시\s*써)\S*\s*(서\s*)?(보여|알려|출력|말해|공개)\w*"
    r"|원문\s*말고\s*요약\S*[^.!?]*"
    r"|(당신|너|네)\S*\s*(주어진|부여된|적힌)\s*(규칙|지시|지침|명령|설정)\S*\s*(목록|리스트)?\S*\s*(을|를)?\s*(번호로\s*)?(나열|출력|알려|보여|공개)\w*"
    r"|(맥락|컨텍스트|대화|기억)\S*\s*(을|를)?\s*(초기화|리셋|reset)\w*[^.!?]*"
    r"|새\s*(세션|대화)\S*\s*(처럼|인\s*것처럼)\s*(행동|답|굴)\w*)", re.I)
INJECTION_NOTICE = "질문에 포함된 지시문(이전 지시 무시, 결과 강요 등)은 따르지 않고, 입력된 수치를 기준에 따라 판정했습니다."


def has_injection(text: str) -> bool:
    """텍스트에 지시문 주입 표현이 있는지 확인한다."""
    return bool(_INJECT.search(text))


def strip_injection(text: str) -> str:
    """지시문 주입 표현을 지우고 나머지(수치 등)는 그대로 둔다."""
    return re.sub(r"\s{2,}", " ", _INJECT.sub(" ", text)).strip()
