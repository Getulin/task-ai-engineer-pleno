from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

_BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "eval"}

class UnsafeQueryError(ValueError):
    """Levantada quando o SQL gerado nao e uma leitura segura."""

@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)

def _strip_sql(sql: str) -> str:
    """Remove cercas Markdown e pontos e virgulas finais."""
    sql = sql.strip()
    if sql.startswith("```") and sql.endswith("```"):
        lines = sql.splitlines()
        if len(lines) >= 3 and lines[0].lower() in {"```", "```sql"} and lines[-1] == "```":
            sql = "\n".join(lines[1:-1]).strip()
    return sql

def validate_read_only(sql: str) -> str:
    """Aceita uma única consulta de leitura, sem comandos ocultos em CTEs."""
    clean = _strip_sql(sql)
    if not clean:
        raise UnsafeQueryError("Consulta vazia.")
    if len(clean) > 16_000:
        raise UnsafeQueryError("A consulta excede o tamanho permitido.")
    try:
        statements = parse(clean, read="sqlite")
    except (SqlglotError, RecursionError) as exc:
        raise UnsafeQueryError("A estrutura do SQL não pôde ser validada.") from exc
    if len(statements) != 1 or statements[0] is None:
        raise UnsafeQueryError("Envie exatamente uma consulta SELECT.")
    query = statements[0]
    if not isinstance(query, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise UnsafeQueryError("Apenas consultas SELECT são permitidas.")
    for node in query.walk():
        if isinstance(node, (exp.DDL, exp.DML, exp.Command, exp.Into)):
            raise UnsafeQueryError("A consulta contém uma operação não autorizada.")
        if isinstance(node, exp.Table) and (node.db or node.catalog):
            raise UnsafeQueryError("Não é permitido consultar outro banco de dados.")
        if isinstance(node, exp.Func):
            name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            if name.lower() in _BLOCKED_FUNCTIONS:
                raise UnsafeQueryError(f"Função não autorizada: {name}.")
    return clean.rstrip(";").strip()

def run_query(db_path: str, sql: str, row_limit: int = 1000,
              timeout_s: float | None = None) -> QueryResult:
    """Executa um SELECT seguro numa conexao read-only e devolve colunas + linhas.

    Erros de SQL do SQLite sobem como sqlite3.Error para o agente tratar/corrigir,
    inclusive a interrupcao por tempo excedido.
    """
    clean = validate_read_only(sql)
    if row_limit < 1:
        raise ValueError("O limite de linhas deve ser positivo.")

    if not Path(db_path).exists():
        raise FileNotFoundError(f"Banco não encontrado: {db_path}")

    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.enable_load_extension(False)

    def authorize(action, arg1, arg2, database, trigger):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and (
            database == "main" or (database is None and arg2 == "")
        ):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_RECURSIVE:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() not in _BLOCKED_FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    conn.set_authorizer(authorize)
    if timeout_s:
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
    try:
        cur = conn.cursor()
        cur.execute(clean)
        fetched = cur.fetchmany(row_limit + 1)
        rows = fetched[:row_limit]
        columns = [d[0] for d in cur.description] if cur.description else []
        return QueryResult(columns=columns, rows=rows, truncated=len(fetched) > row_limit)
    except sqlite3.OperationalError as exc:
        if timeout_s and "interrupted" in str(exc).lower():
            raise sqlite3.OperationalError(
                f"A consulta excedeu {timeout_s:g}s e foi interrompida. "
                "Simplifique os JOINs ou agregue antes de cruzar tabelas."
            ) from exc
        raise
    finally:
        conn.close()

