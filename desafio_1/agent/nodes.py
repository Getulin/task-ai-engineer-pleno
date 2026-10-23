from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from . import prompts
from .config import Settings
from .db import UnsafeQueryError, run_query, validate_read_only
from .schema import discover_schema
from .state import AgentState

_MAX_REVIEW_RETRIES = 1

def _text(response: Any) -> str:
    """Converte o conteudo da resposta do modelo em texto."""
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content).strip()

def _parse_json(text: str) -> dict:
    """Lê o primeiro objeto JSON da resposta."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError(f"Sem objeto JSON na resposta: {text[:200]}")

def _append_trace(state: AgentState, step: str, detail: str, data: Any = None) -> list:
    trace = list(state.get("trace", []))
    trace.append({"step": step, "detail": detail, "data": data})
    return trace

def make_nodes(llm: BaseChatModel, settings: Settings) -> dict:
    """Cria os nos com o LLM e as settings injetados (closures)."""

    def discover(state: AgentState) -> AgentState:
        schema = discover_schema(settings.db_abspath)
        return {
            "schema": schema,
            "repair_count": 0,
            "review_count": 0,
            "trace": _append_trace(
                state, "descoberta_schema",
                "Inspecionei o banco dinamicamente (tabelas, colunas e valores reais).",
            ),
        }

    def generate_sql(state: AgentState) -> AgentState:
        system = SystemMessage(prompts.SQL_SYSTEM.format(schema=state["schema"]))
        patch: dict = {}

        if state.get("review_needed"):
            context = state.get("review_context") or {}
            human = HumanMessage(prompts.SQL_REVIEW.format(
                question=state["question"],
                sql=context.get("sql", ""),
                result=json.dumps(context.get("result", {}), ensure_ascii=False),
                feedback=state.get("review_feedback") or "",
            ))
            detail = "Revisei a consulta após verificar a aderência à pergunta."
            patch["review_needed"] = False
            patch["repair_count"] = 0
        elif state.get("reconsider_empty"):
            human = HumanMessage(prompts.SQL_RECONSIDER_EMPTY.format(
                question=state["question"], sql=state.get("sql", ""),
            ))
            detail = f"Resultado vazio: reconsiderando suposicoes (tentativa #{state.get('empty_retries', 0)})."
            patch["reconsider_empty"] = False
        elif state.get("error"):
            human = HumanMessage(prompts.SQL_REPAIR.format(
                question=state["question"], sql=state.get("sql", ""),
                error=state.get("error", ""),
            ))
            detail = f"Tentativa de correcao #{state.get('repair_count', 0)} apos erro."
        else:
            human = HumanMessage(state["question"])
            detail = "Gerei a consulta SQL inicial a partir da pergunta."

        sql = _text(llm.invoke([system, human]))
        try:
            sql = validate_read_only(sql)
        except UnsafeQueryError:
            pass
        patch["sql"] = sql
        patch["trace"] = _append_trace(state, "gerar_sql", detail, sql)
        return patch

    def execute_sql(state: AgentState) -> AgentState:
        sql = state.get("sql", "")
        try:
            result = run_query(settings.db_abspath, sql, settings.row_limit)
            return {
                "result_columns": result.columns,
                "result_rows": result.rows,
                "result_truncated": result.truncated,
                "error": None,
                "last_was_empty": result.row_count == 0,
                "trace": _append_trace(
                    state, "executar_sql",
                    f"Consulta executada: {result.row_count} linha(s) carregada(s).",
                    {"sql": sql, "row_count": result.row_count,
                     "truncated": result.truncated},
                ),
            }
        except (sqlite3.Error, UnsafeQueryError, FileNotFoundError, ValueError) as exc:
            return {
                "error": str(exc),
                "result_columns": [],
                "result_rows": [],
                "result_truncated": False,
                "last_was_empty": False,
                "repair_count": state.get("repair_count", 0) + 1,
                "trace": _append_trace(
                    state, "erro_execucao",
                    f"Erro ao executar o SQL: {exc}",
                    {"sql": sql, "error": str(exc)},
                ),
            }

    def assess_result(state: AgentState) -> AgentState:
        columns = state.get("result_columns", [])
        rows = state.get("result_rows", [])
        result = {
            "columns": columns,
            "rows": [list(row) for row in rows[:10]],
            "loaded_rows": len(rows),
            "truncated": state.get("result_truncated", False),
        }
        context = {"sql": state.get("sql", ""), "result": result}
        try:
            messages = [
                SystemMessage(prompts.ASSESS_SYSTEM),
                HumanMessage(prompts.ASSESS_HUMAN.format(
                    question=state["question"],
                    sql=state.get("sql", ""),
                    result=json.dumps(result, ensure_ascii=False),
                )),
            ]
            assessment = _parse_json(_text(llm.invoke(messages)))
            sufficient = assessment.get("sufficient")
            if not isinstance(sufficient, bool):
                raise ValueError("A avaliação não trouxe um booleano.")
            feedback = str(assessment.get("feedback") or "").strip()[:500]
        except Exception:
            sufficient, feedback = True, "Avaliação indisponível; consulta mantida."

        if sufficient:
            return {
                "review_needed": False,
                "review_feedback": None,
                "trace": _append_trace(state, "verificar_resultado",
                                       "A consulta foi considerada suficiente."),
            }

        count = state.get("review_count", 0) + 1
        if count <= _MAX_REVIEW_RETRIES:
            return {
                "review_count": count,
                "review_needed": True,
                "review_feedback": feedback,
                "review_context": context,
                "trace": _append_trace(
                    state, "verificar_resultado",
                    "A consulta não respondeu completamente à pergunta; nova consulta necessária.",
                    feedback,
                ),
            }
        return {
            "review_count": count,
            "review_needed": False,
            "final_issue": "Não foi possível confirmar uma resposta confiável após revisar a consulta.",
            "trace": _append_trace(state, "verificar_resultado",
                                   "A revisão não encontrou uma consulta suficiente.", feedback),
        }

    def decide_viz(state: AgentState) -> AgentState:
        columns = state.get("result_columns", [])
        rows = state.get("result_rows", [])
        sample = [dict(zip(columns, r)) for r in rows[:5]]
        spec = _heuristic_viz(state["question"], columns, rows)
        try:
            messages = [
                SystemMessage(prompts.VIZ_SYSTEM),
                HumanMessage(prompts.VIZ_HUMAN.format(
                    question=state["question"], columns=columns,
                    sample=sample, n_rows=len(rows),
                )),
            ]
            parsed = _parse_json(_text(llm.invoke(messages)))
            spec = _sanitize_viz(parsed, columns, rows, fallback=spec)
        except Exception:
            pass
        return {
            "viz": spec,
            "trace": _append_trace(
                state, "decidir_visualizacao",
                f"Escolhi exibir como '{spec['type']}'.", spec,
            ),
        }

    def synthesize(state: AgentState) -> AgentState:
        if state.get("final_issue"):
            return {
                "answer": state["final_issue"],
                "trace": _append_trace(state, "resposta", "Resposta não confirmada."),
            }
        if state.get("error"):
            answer = prompts.ANSWER_FAILURE.format(
                question=state["question"], error=state.get("error", ""),
            )
            return {"answer": answer,
                    "trace": _append_trace(state, "resposta", "Falha apos tentativas de correcao.")}

        columns = state.get("result_columns", [])
        rows = state.get("result_rows", [])
        preview = {
            "columns": columns,
            "rows": [list(r) for r in rows[:50]],
            "loaded_rows": len(rows),
            "more_rows": len(rows) > 50 or state.get("result_truncated", False),
        }
        messages = [
            SystemMessage(prompts.ANSWER_SYSTEM),
            HumanMessage(prompts.ANSWER_HUMAN.format(
                question=state["question"], sql=state.get("sql", ""),
                result=json.dumps(preview, ensure_ascii=False),
            )),
        ]
        answer = _text(llm.invoke(messages))
        return {"answer": answer,
                "trace": _append_trace(state, "resposta", "Sintetizei a resposta final em linguagem natural.")}

    def reconsider(state: AgentState) -> AgentState:
        return {
            "reconsider_empty": True,
            "empty_retries": state.get("empty_retries", 0) + 1,
            "trace": _append_trace(
                state, "reflexao_vazio",
                "Resultado vazio inesperado: vou reconsiderar as suposicoes.",
            ),
        }

    return {
        "discover": discover,
        "generate_sql": generate_sql,
        "execute_sql": execute_sql,
        "reconsider": reconsider,
        "assess_result": assess_result,
        "decide_viz": decide_viz,
        "synthesize": synthesize,
    }

_DATE_HINT = re.compile(r"(data|ano|mes|mês|periodo|período)", re.IGNORECASE)

def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def _heuristic_viz(question: str, columns: list[str], rows: list[tuple]) -> dict:
    if not columns or not rows:
        return {"type": "table", "x": None, "y": None, "series": None, "title": "Resultado"}
    if len(columns) == 3 and all(_is_number(r[2]) for r in rows):
        x, series, y = columns
        if _DATE_HINT.search(x) or _DATE_HINT.search(question):
            return {"type": "line", "x": x, "y": y, "series": series,
                    "title": question[:60]}
        return {"type": "bar", "x": x, "y": y, "series": series,
                "title": question[:60]}
    if len(columns) == 2:
        x, y = columns[0], columns[1]
        y_is_num = all(_is_number(r[1]) for r in rows[:20])
        if y_is_num:
            if _DATE_HINT.search(x) or _DATE_HINT.search(question):
                return {"type": "line", "x": x, "y": y, "series": None,
                        "title": question[:60]}
            return {"type": "bar", "x": x, "y": y, "series": None,
                    "title": question[:60]}
    return {"type": "table", "x": None, "y": None, "series": None,
            "title": "Resultado"}

def _sanitize_viz(parsed: dict, columns: list[str], rows: list[tuple], fallback: dict) -> dict:
    vtype = parsed.get("type")
    if vtype not in ("table", "bar", "line"):
        return fallback
    x = parsed.get("x") if parsed.get("x") in columns else None
    y = parsed.get("y") if parsed.get("y") in columns else None
    series = parsed.get("series")
    if series not in columns or series in (x, y):
        series = None
    if vtype in ("bar", "line") and (
        x is None or y is None or
        not all(_is_number(row[columns.index(y)]) for row in rows)
    ):
        return fallback
    title = str(parsed.get("title") or "Resultado")[:80]
    return {"type": vtype, "x": x, "y": y, "series": series, "title": title}

