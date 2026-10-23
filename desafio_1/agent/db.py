from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|"
    r"ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|GRANT)\b",
    re.IGNORECASE,
)

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
    sql = re.sub(r"^```(?:sql)?|```$", "", sql, flags=re.IGNORECASE | re.MULTILINE)
    sql = sql.strip()
    return sql.rstrip(";").strip()

def validate_read_only(sql: str) -> str:
    """Valida e normaliza o SQL. Retorna o SQL limpo ou levanta UnsafeQueryError."""
    clean = _strip_sql(sql)
    if not clean:
        raise UnsafeQueryError("Consulta vazia.")

    if ";" in clean:
        raise UnsafeQueryError("Multiplas instrucoes nao sao permitidas.")

    lowered = clean.lstrip("(").lstrip().lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise UnsafeQueryError("Apenas consultas SELECT/WITH sao permitidas.")

    if _FORBIDDEN.search(clean):
        raise UnsafeQueryError("A consulta contem uma operacao de escrita/DDL proibida.")

    return clean

def run_query(db_path: str, sql: str, row_limit: int = 1000) -> QueryResult:
    """Executa um SELECT seguro numa conexao read-only e devolve colunas + linhas.

    Erros de SQL do SQLite sobem como sqlite3.Error para o agente tratar/corrigir.
    """
    clean = validate_read_only(sql)
    if row_limit < 1:
        raise ValueError("O limite de linhas deve ser positivo.")

    if not Path(db_path).exists():
        raise FileNotFoundError(f"Banco nao encontrado: {db_path}")

    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.cursor()
        cur.execute(clean)
        fetched = cur.fetchmany(row_limit + 1)
        rows = fetched[:row_limit]
        columns = [d[0] for d in cur.description] if cur.description else []
        return QueryResult(columns=columns, rows=rows, truncated=len(fetched) > row_limit)
    finally:
        conn.close()

