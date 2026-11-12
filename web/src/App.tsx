// App.tsx - 질문 입력 → 답변·근거 지침·처리 과정 표시 화면
import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { postQuery, type Context, type QueryResponse } from './api'
import TracePanel from './TracePanel'

const MAX_LEN = 500

const EXAMPLES = [
  '공복혈당 112 mg/dL이면 어떤 상태인가요?',
  '혈압 135/85, LDL 콜레스테롤 165인데 생활습관은 어떻게 바꿔야 하나요?',
  '키 170cm, 몸무게 82kg, 허리둘레 92cm 남성입니다.',
  'ALT 58, 감마지티피 80이 나왔어요. 관리 지침이 궁금해요.',
]

type State =
  | { kind: 'idle' }
  | { kind: 'loading'; question: string }
  | { kind: 'error'; question: string; message: string }
  | { kind: 'done'; question: string; data: QueryResponse }

function contextOf(c: Context | string): Context {
  return typeof c === 'string' ? { doc_id: '지침', text: c } : c
}

function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

export default function App() {
  const [question, setQuestion] = useState('')
  const [state, setState] = useState<State>({ kind: 'idle' })
  const abortRef = useRef<AbortController | null>(null)

  const loading = state.kind === 'loading'
  const trimmed = question.trim()
  const tooLong = question.length > MAX_LEN

  async function submit(q: string) {
    if (!q.trim() || q.length > MAX_LEN || loading) return
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setState({ kind: 'loading', question: q })
    try {
      const data = await postQuery(q, ctrl.signal)
      setState({ kind: 'done', question: q, data })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setState({ kind: 'error', question: q, message: err instanceof Error ? err.message : String(err) })
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    void submit(question)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      void submit(question)
    }
  }

  function cancel() {
    abortRef.current?.abort()
    setState({ kind: 'idle' })
  }

  return (
    <div className="page">
      <header className="header">
        <div className="logo" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
        </div>
        <div>
          <h1>건강검진 수치 해석 어시스턴트</h1>
          <p className="subtitle">검진 수치를 입력하면 기준에 따라 정상·경계·질환의심을 판정하고, 생활습관 지침을 근거와 함께 알려 드립니다.</p>
        </div>
      </header>

      <main className="main">
        <form className="card ask" onSubmit={onSubmit}>
          <label htmlFor="question" className="field-label">질문</label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            rows={4}
            placeholder="예: 공복혈당 112, 총콜레스테롤 230인데 괜찮은가요?"
            aria-describedby="question-help"
            aria-invalid={tooLong}
          />
          <div className="ask-footer">
            <span id="question-help" className={tooLong ? 'error-text small' : 'muted small'}>
              {tooLong ? `${MAX_LEN}자 이내로 입력해 주세요.` : '항목·수치·단위, 성별·공복 여부를 함께 적으면 더 정확합니다. Ctrl+Enter로 보내기'}
              <span className="counter"> {question.length}/{MAX_LEN}</span>
            </span>
            <div className="actions">
              {loading && (
                <button type="button" className="btn btn-ghost" onClick={cancel}>취소</button>
              )}
              <button type="submit" className="btn btn-primary" disabled={!trimmed || tooLong || loading}>
                {loading ? <><Spinner /> 분석 중</> : '질문하기'}
              </button>
            </div>
          </div>
          <div className="examples" aria-label="예시 질문">
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="chip chip-btn" disabled={loading} onClick={() => setQuestion(ex)}>
                {ex}
              </button>
            ))}
          </div>
        </form>

        <div aria-live="polite">
          {state.kind === 'loading' && (
            <section className="card" aria-busy="true">
              <p className="status-line"><Spinner /> 수치를 판정하고 지침을 찾는 중입니다. 수십 초 걸릴 수 있습니다.</p>
              <div className="skeleton" />
              <div className="skeleton short" />
              <div className="skeleton" />
            </section>
          )}

          {state.kind === 'error' && (
            <section className="card error-card" role="alert">
              <h2>답변을 받지 못했습니다</h2>
              <p>{state.message}</p>
              <p className="muted small">백엔드 실행: 프로젝트 루트에서 <code>uvicorn src.app:app --port 8000</code></p>
              <button type="button" className="btn btn-primary" onClick={() => void submit(state.question)}>다시 시도</button>
            </section>
          )}
        </div>

        {state.kind === 'done' && (
          <>
            <section className="card">
              <p className="asked"><span className="muted">질문</span> {state.question}</p>
              <h2>답변</h2>
              <div className="markdown">
                <Markdown remarkPlugins={[remarkGfm]}>{state.data.answer}</Markdown>
              </div>
            </section>

            <section className="card">
              <h2>근거 지침 <span className="count">{state.data.contexts.length}</span></h2>
              {state.data.contexts.length === 0 ? (
                <p className="muted">이 답변에 사용된 지침 문서가 없습니다.</p>
              ) : (
                <ul className="context-list">
                  {state.data.contexts.map((raw, i) => {
                    const c = contextOf(raw)
                    return (
                      <li key={i}>
                        <details>
                          <summary>
                            <span className="doc-id">{c.doc_id}</span>
                            <span className="preview">{c.text.slice(0, 80)}</span>
                          </summary>
                          <div className="markdown context-text">
                            <Markdown remarkPlugins={[remarkGfm]}>{c.text}</Markdown>
                          </div>
                        </details>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>

            <section className="card">
              <h2>판정·도구 호출 과정 <span className="count">{state.data.trace.length}</span></h2>
              <p className="muted small">각 단계를 눌러 입력과 출력 원문을 볼 수 있습니다.</p>
              <TracePanel trace={state.data.trace} />
            </section>
          </>
        )}
      </main>

      <footer className="footer muted small">
        이 서비스는 진단이나 처방을 하지 않습니다. 정확한 판단은 의료기관에서 상담해 주세요.
      </footer>
    </div>
  )
}
