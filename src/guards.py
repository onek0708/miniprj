"""입력 가드, 출력 가드 (현재는 입력 가드의 차단 감지만 구현)."""
import re

# 약·용량·건강기능식품 요청 (G2)
_DRUG = re.compile(r"(약\s*(을|좀)?\s*(추천|처방|먹|복용)|처방|복용량|용량|영양제|건강기능식품|보충제|\d+\s*(mg|밀리그램))")
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


# 개인정보 (G4): 주민등록번호, 전화번호
_RRN = re.compile(r"(?<!\d)\d{6}\s*[-‐-―~.\s]\s*[1-8]\d{6}(?!\d)|(?<!\d)\d{6}[1-4]\d{6}(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+82[-.\s]?)?0\d{1,2}[-.\s)]*\d{3,4}[-.\s]*\d{4}(?!\d)")
PII_MASK = "[개인정보 삭제]"
PII_NOTICE = "입력하신 주민등록번호·전화번호 같은 개인정보는 답변에 사용하거나 반복하지 않습니다."


def redact_pii(text: str) -> str:
    """주민등록번호·전화번호를 가린다."""
    return _PHONE.sub(PII_MASK, _RRN.sub(PII_MASK, text))


def has_pii(text: str) -> bool:
    """텍스트에 주민등록번호·전화번호가 있는지 확인한다."""
    return redact_pii(text) != text


# 지시문 주입 (G5): 차단하지 않고 지시 부분만 지운 뒤 수치는 정상 판정한다
_INJECT = re.compile(
    r"((이전|위|앞|기존|모든|지금까지의?)\s*(의\s*)?(지시|지침|명령|프롬프트|규칙|설정)\w*\s*(을|를|은|는)?\s*(모두\s*|전부\s*)?"
    r"(무시|잊어|잊고|따르지\s*(말|마))\w*\s*(하고|해서|하세요|해|해라|해줘)?[,\s]*"
    r"((무조건|항상|그냥|일단)?\s*(전부\s*)?(정상|괜찮다|문제\s*없다)\w*\s*(이?라고|고)?\s*(답|말|대답|출력|판정)\w*)?"
    r"|ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions?|prompts?)[^.!?\n]*"
    r"|시스템\s*프롬프트\s*(를|을)?\s*(공개|출력|보여)\w*"
    r"|(무조건|항상)\s*(정상|괜찮다)\w*\s*(이?라고)?\s*(답|말|대답)\w*)", re.I)
INJECTION_NOTICE = "질문에 포함된 지시문(이전 지시 무시, 결과 강요 등)은 따르지 않고, 입력된 수치를 기준에 따라 판정했습니다."


def has_injection(text: str) -> bool:
    """텍스트에 지시문 주입 표현이 있는지 확인한다."""
    return bool(_INJECT.search(text))


def strip_injection(text: str) -> str:
    """지시문 주입 표현을 지우고 나머지(수치 등)는 그대로 둔다."""
    return re.sub(r"\s{2,}", " ", _INJECT.sub(" ", text)).strip()
