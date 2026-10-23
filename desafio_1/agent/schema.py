from __future__ import annotations

import calendar
import re
import sqlite3
from pathlib import Path

_MAX_DISTINCT_FOR_ENUM = 25
_SAMPLE_EXAMPLES = 3
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NUMERIC_TYPES = ("INT", "REAL", "NUM", "FLOAT", "DOUBLE", "DEC")

def _is_numeric(col_type: str) -> bool:
    return any(t in (col_type or "").upper() for t in _NUMERIC_TYPES)

def _connect_ro(db_path: str) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)

def _user_tables(cur: sqlite3.Cursor) -> list[str]:
    return [
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]

def _date_range(cur: sqlite3.Cursor, table: str, col: str) -> tuple[str, str] | None:
    """Retorna (min, max) se a coluna guarda datas YYYY-MM-DD em texto."""
    quoted = f'"{col}"'
    sample = cur.execute(
        f"SELECT {quoted} FROM '{table}' WHERE {quoted} IS NOT NULL LIMIT 1"
    ).fetchone()
    if not sample or not _DATE_RE.match(str(sample[0])):
        return None
    first, last = cur.execute(
        f"SELECT MIN({quoted}), MAX({quoted}) FROM '{table}' WHERE {quoted} IS NOT NULL"
    ).fetchone()
    return str(first)[:10], str(last)[:10]

def _partial_months(first: str, last: str) -> list[tuple[str, str]]:
    """Meses de borda que nao estao inteiros no intervalo [first, last]."""
    found = []
    year, month, day = map(int, first.split("-"))
    if day != 1:
        found.append((first[:7], f"a partir do dia {day:02d}"))
    year, month, day = map(int, last.split("-"))
    if day != calendar.monthrange(year, month)[1]:
        found.append((last[:7], f"ate o dia {day:02d}"))
    return found

def find_partial_months(db_path: str) -> list[str]:
    """Meses (YYYY-MM) que aparecem incompletos em alguma coluna de data."""
    conn = _connect_ro(db_path)
    try:
        cur = conn.cursor()
        months: set[str] = set()
        for table in _user_tables(cur):
            for _, col, col_type, *_ in cur.execute(f"PRAGMA table_info('{table}')").fetchall():
                if _is_numeric(col_type):
                    continue
                bounds = _date_range(cur, table, col)
                if bounds:
                    months.update(m for m, _ in _partial_months(*bounds))
        return sorted(months)
    finally:
        conn.close()

def discover_schema(db_path: str) -> str:
    """Monta uma descricao textual do schema para o prompt do LLM."""
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Banco nao encontrado: {db_path}")

    conn = _connect_ro(db_path)
    try:
        cur = conn.cursor()
        blocks: list[str] = []
        for table in _user_tables(cur):
            blocks.append(_describe_table(cur, table))
        return "\n\n".join(blocks)
    finally:
        conn.close()

def _describe_table(cur: sqlite3.Cursor, table: str) -> str:
    cols = cur.execute(f"PRAGMA table_info('{table}')").fetchall()
    n_rows = cur.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]

    lines = [f"Tabela: {table}  ({n_rows} linhas)"]
    for _, name, col_type, _, _, pk in cols:
        hint = _column_hint(cur, table, name, col_type)
        pk_tag = " [PK]" if pk else ""
        lines.append(f"  - {name} ({col_type or 'TEXT'}){pk_tag}{hint}")

    fks = cur.execute(f"PRAGMA foreign_key_list('{table}')").fetchall()
    for fk in fks:
        lines.append(f"  - FK: {fk[3]} -> {fk[2]}.{fk[4]}")

    return "\n".join(lines)

def _column_hint(cur: sqlite3.Cursor, table: str, col: str, col_type: str) -> str:
    """Enriquece a coluna com valores reais do banco (enum, exemplos, min/max)."""
    quoted = f'"{col}"'

    if _is_numeric(col_type):
        row = cur.execute(
            f"SELECT MIN({quoted}), MAX({quoted}) FROM '{table}' "
            f"WHERE {quoted} IS NOT NULL"
        ).fetchone()
        if row and row[0] is not None:
            return f"  -> intervalo: {row[0]} a {row[1]}"
        return ""

    bounds = _date_range(cur, table, col)
    if bounds:
        hint = f"  -> datas de {bounds[0]} ate {bounds[1]} (formato YYYY-MM-DD)"
        partial = _partial_months(*bounds)
        if partial:
            hint += "; meses parciais: " + ", ".join(f"{m} ({d})" for m, d in partial)
        return hint

    try:
        distinct = cur.execute(
            f"SELECT COUNT(DISTINCT {quoted}) FROM '{table}'"
        ).fetchone()[0]
    except sqlite3.Error:
        return ""

    if distinct == 0:
        return ""

    if distinct <= _MAX_DISTINCT_FOR_ENUM:
        vals = [
            str(r[0])
            for r in cur.execute(
                f"SELECT DISTINCT {quoted} FROM '{table}' "
                f"WHERE {quoted} IS NOT NULL ORDER BY {quoted}"
            ).fetchall()
        ]
        return f"  -> valores possiveis: {vals}"

    examples = [
        str(r[0])
        for r in cur.execute(
            f"SELECT {quoted} FROM '{table}' WHERE {quoted} IS NOT NULL LIMIT {_SAMPLE_EXAMPLES}"
        ).fetchall()
    ]
    return f"  -> exemplos ({distinct} distintos): {examples}"

