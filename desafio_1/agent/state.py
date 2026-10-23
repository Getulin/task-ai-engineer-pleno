from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

VizType = Literal["table", "bar", "line"]
AnswerStatus = Literal["confirmed", "assumption", "unconfirmed", "unverified"]

class VizSpec(TypedDict):
    type: VizType
    x: Optional[str]
    y: Optional[str]
    series: Optional[str]
    title: str

class TraceStep(TypedDict):
    step: str
    detail: str
    data: Any

class AgentState(TypedDict, total=False):
    question: str

    schema: str
    partial_months: list[str]

    sql: str
    result_columns: list[str]
    result_rows: list[tuple]
    error: Optional[str]
    repair_count: int
    result_truncated: bool

    last_was_empty: bool
    empty_retries: int
    reconsider_empty: bool
    review_count: int
    review_needed: bool
    review_feedback: Optional[str]
    review_context: Optional[dict]
    review_history: list[dict]
    assumptions: list[str]
    caveat: Optional[str]
    answer_status: Optional[AnswerStatus]

    viz: VizSpec
    answer: str
    data_notes: list[str]

    trace: list[TraceStep]

