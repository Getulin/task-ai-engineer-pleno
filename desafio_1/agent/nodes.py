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

def _text(response: Any) -> str:
    """Converte o conteudo da resposta do modelo em texto."""
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content).strip()

def _parse_json(text: str) -> dict:
    """Extrai o primeiro objeto JSON do texto, tolerante a lixo ao redor."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Sem JSON na resposta: {text[:200]}")
    return json.loads(match.group(0))

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
            "trace": _append_trace(
                state, "descoberta_schema",
                "Inspecionei o banco dinamicamente (tabelas, colunas e valores reais).",
            ),
        }

    def generate_sql(state: AgentState) -> AgentState:
        is_repair = bool(state.get("error"))
        if is_repair:
            messages = [
                SystemMessage(prompts.SQL_SYSTEM.format(schema=state["schema"])),
                HumanMessage(prompts.SQL_REPAIR.format(
                    question=state["question"],
                    sql=state.get("sql", ""),
                    error=state.get("error", ""),
                )),
            ]
            detail = f"Tentativa de correcao #{state.get('repair_count', 0)} apos erro."
        else:
            messages = [
                SystemMessage(prompts.SQL_SYSTEM.format(schema=state["schema"])),
                HumanMessage(state["question"]),
            ]
            detail = "Gerei a consulta SQL inicial a partir da pergunta."

        sql = _text(llm.invoke(messages))
        try:
            sql = validate_read_only(sql)
        except UnsafeQueryError:
            pass
        return {"sql": sql, "trace": _append_trace(state, "gerar_sql", detail, sql)}

    def execute_sql(state: AgentState) -> AgentState:
        sql = state.get("sql", "")
        try:
            result = run_query(settings.db_abspath, sql, settings.row_limit)
            return {
                "result_columns": result.columns,
                "result_rows": result.rows,
                "error": None,
                "trace": _append_trace(
                    state, "executar_sql",
                    f"Consulta executada com sucesso: {result.row_count} linha(s).",
                    {"sql": sql, "row_count": result.row_count},
                ),
            }
        except (sqlite3.Error, UnsafeQueryError, FileNotFoundError, ValueError) as exc:
            return {
                "error": str(exc),
                "repair_count": state.get("repair_count", 0) + 1,
                "trace": _append_trace(
                    state, "erro_execucao",
                    f"Erro ao executar o SQL: {exc}",
                    {"sql": sql, "error": str(exc)},
                ),
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
        if state.get("error"):
            answer = prompts.ANSWER_FAILURE.format(
                question=state["question"], error=state.get("error", ""),
            )
            return {"answer": answer,
                    "trace": _append_trace(state, "resposta", "Falha apos tentativas de correcao.")}

        columns = state.get("result_columns", [])
        rows = state.get("result_rows", [])
        preview = {"columns": columns, "rows": [list(r) for r in rows[:50]]}
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

    return {
        "discover": discover,
        "generate_sql": generate_sql,
        "execute_sql": execute_sql,
        "decide_viz": decide_viz,
        "synthesize": synthesize,
    }

_DATE_HINT = re.compile(r"(data|ano|mes|mês|periodo|período)", re.IGNORECASE)

def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def _heuristic_viz(question: str, columns: list[str], rows: list[tuple]) -> dict:
    if not columns or not rows:
        return {"type": "table", "x": None, "y": None, "title": "Resultado"}
    if len(columns) == 2:
        x, y = columns[0], columns[1]
        y_is_num = all(_is_number(r[1]) for r in rows[:20])
        if y_is_num:
            if _DATE_HINT.search(x) or _DATE_HINT.search(question):
                return {"type": "line", "x": x, "y": y, "title": question[:60]}
            return {"type": "bar", "x": x, "y": y, "title": question[:60]}
    return {"type": "table", "x": None, "y": None, "title": "Resultado"}

def _sanitize_viz(parsed: dict, columns: list[str], rows: list[tuple], fallback: dict) -> dict:
    vtype = parsed.get("type")
    if vtype not in ("table", "bar", "line"):
        return fallback
    x = parsed.get("x") if parsed.get("x") in columns else None
    y = parsed.get("y") if parsed.get("y") in columns else None
    if vtype in ("bar", "line") and (
        x is None or y is None or
        not all(_is_number(row[columns.index(y)]) for row in rows)
    ):
        return fallback
    title = str(parsed.get("title") or "Resultado")[:80]
    return {"type": vtype, "x": x, "y": y, "title": title}

