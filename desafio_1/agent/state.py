from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

VizType = Literal["table", "bar", "line"]

class VizSpec(TypedDict):
    type: VizType
    x: Optional[str]
    y: Optional[str]
    title: str

class TraceStep(TypedDict):
    step: str
    detail: str
    data: Any

class AgentState(TypedDict, total=False):
    question: str

    schema: str

    sql: str
    result_columns: list[str]
    result_rows: list[tuple]
    error: Optional[str]
    repair_count: int

    last_was_empty: bool
    empty_retries: int
    reconsider_empty: bool

    viz: VizSpec
    answer: str

    trace: list[TraceStep]

