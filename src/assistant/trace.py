"""도구 호출 기록(패턴 11)."""
import json


class _Recorder:
    """도구 호출을 trace 단계와 contexts로 기록한다 (패턴 11)."""

    def __init__(self):
        self.trace: list[dict] = []
        self.contexts: list[dict] = []

    def step(self, name: str, inp, out: str):
        self.trace.append({"step": name, "input": inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False),
                           "output": out})
