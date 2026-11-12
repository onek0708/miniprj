// TracePanel.tsx - 판정·도구 호출 과정(trace)을 단계별로 펼쳐 보는 영역
import type { TraceStep } from './api'

const STEP_LABELS: Record<string, string> = {
  input_guard: '입력 가드',
  judge_checkup_item: '항목 판정',
  calc_bmi: '체질량지수 계산',
  retrieve_guides: '지침 검색',
  error: '오류',
}

const GUARD_LABELS: Record<string, string> = {
  G1_diagnosis: '진단 확정 요청',
  G2_drug: '약·용량·건강기능식품 요청',
  G4_pii: '개인정보 포함',
  G5_injection: '지시문 주입',
}

type Band = '정상' | '경계' | '질환의심'

interface JudgeResult {
  status: '판정' | '보류'
  item: string
  value?: number | string
  unit?: string | null
  band?: Band | null
  reason?: string
  by_sex?: Record<string, { status: string; band?: Band | null; reason?: string }>
  assumptions?: string[]
}

interface BmiResult {
  status: '계산' | '보류'
  bmi?: number | null
  reason?: string
}

/** JSON 문자열이면 객체로, 아니면 null로 돌려준다. */
function parseJson<T>(text: string): T | null {
  try {
    const v: unknown = JSON.parse(text)
    return v && typeof v === 'object' ? (v as T) : null
  } catch {
    return null
  }
}

function BandBadge({ band }: { band?: Band | null }) {
  if (!band) return <span className="badge badge-hold">보류</span>
  const cls = band === '정상' ? 'badge-ok' : band === '경계' ? 'badge-warn' : 'badge-alert'
  return <span className={`badge ${cls}`}>{band}</span>
}

/** 단계 종류별 한 줄 요약 */
function Summary({ step }: { step: TraceStep }) {
  if (step.step === 'judge_checkup_item') {
    const r = parseJson<JudgeResult>(step.output)
    if (!r) return <span className="muted">{step.output}</span>
    const value = `${r.value ?? ''}${r.unit ?? ''}`
    if (r.status !== '판정') {
      return (
        <span>
          {r.item} {value} <BandBadge band={null} />
        </span>
      )
    }
    if (r.by_sex) {
      return (
        <span className="summary-row">
          {r.item} {value}
          {Object.entries(r.by_sex).map(([sex, v]) => (
            <span key={sex} className="sex-band">
              {sex} <BandBadge band={v.status === '판정' ? v.band : null} />
            </span>
          ))}
        </span>
      )
    }
    return (
      <span>
        {r.item} {value} <BandBadge band={r.band} />
      </span>
    )
  }
  if (step.step === 'calc_bmi') {
    const r = parseJson<BmiResult>(step.output)
    if (r?.status === '계산' && r.bmi != null) return <span>BMI {r.bmi}</span>
    return <span className="muted">{r?.reason ?? step.output}</span>
  }
  if (step.step === 'input_guard') {
    const detected = step.detected ?? []
    return (
      <span className="summary-row">
        <span className={`badge ${step.blocked ? 'badge-alert' : 'badge-ok'}`}>
          {step.blocked ? '차단' : '통과'}
        </span>
        {detected.length > 0
          ? detected.map((d) => (
              <span key={d} className="chip">
                {GUARD_LABELS[d] ?? d}
              </span>
            ))
          : <span className="muted">감지 없음</span>}
      </span>
    )
  }
  return <span className={step.step === 'error' ? 'error-text' : ''}>{step.output}</span>
}

/** input·output 원문을 보기 좋게 (JSON이면 들여쓰기) 보여 준다. */
function Raw({ label, text }: { label: string; text: string }) {
  if (!text) return null
  const obj = parseJson<object>(text)
  return (
    <div className="raw">
      <div className="raw-label">{label}</div>
      <pre>{obj ? JSON.stringify(obj, null, 2) : text}</pre>
    </div>
  )
}

export default function TracePanel({ trace }: { trace: TraceStep[] }) {
  if (trace.length === 0) return <p className="muted">기록된 처리 단계가 없습니다.</p>
  return (
    <ol className="trace-list">
      {trace.map((step, i) => (
        <li key={i} className={`trace-item trace-${step.step}`}>
          <details>
            <summary>
              <span className="step-index" aria-hidden="true">{i + 1}</span>
              <span className="step-name">{STEP_LABELS[step.step] ?? step.step}</span>
              <span className="step-summary">
                <Summary step={step} />
              </span>
            </summary>
            <div className="step-body">
              <Raw label="입력" text={step.input} />
              <Raw label="출력" text={step.output} />
            </div>
          </details>
        </li>
      ))}
    </ol>
  )
}
