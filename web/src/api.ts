// api.ts - 백엔드 POST /query 호출과 응답 타입

/** 근거 지침 조각 (retrieve_guides 결과) */
export interface Context {
  doc_id: string
  text: string
}

/** 처리 과정 한 단계. input_guard 단계에는 detected·blocked가 더 붙는다. */
export interface TraceStep {
  step: string
  input: string
  output: string
  detected?: string[]
  blocked?: boolean
}

/** POST /query 응답 (제출 규약: answer, contexts, trace) */
export interface QueryResponse {
  answer: string
  contexts: (Context | string)[]
  trace: TraceStep[]
}

/** 질문을 보내고 세 키 응답을 받는다. 네트워크·HTTP 오류는 예외로 던진다. */
export async function postQuery(question: string, signal?: AbortSignal): Promise<QueryResponse> {
  let res: Response
  try {
    res = await fetch('/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
      signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new Error('서버에 연결하지 못했습니다. 백엔드(uvicorn)가 켜져 있는지 확인해 주세요.')
  }
  if (!res.ok) {
    throw new Error(
      res.status >= 500
        ? `서버 오류가 발생했습니다 (HTTP ${res.status}). 백엔드가 켜져 있는지 확인해 주세요.`
        : `요청이 거부되었습니다 (HTTP ${res.status}).`,
    )
  }
  const data = (await res.json()) as Partial<QueryResponse>
  if (typeof data.answer !== 'string') throw new Error('응답 형식이 올바르지 않습니다.')
  return {
    answer: data.answer,
    contexts: Array.isArray(data.contexts) ? data.contexts : [],
    trace: Array.isArray(data.trace) ? data.trace : [],
  }
}
