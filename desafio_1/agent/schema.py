from __future__ import annotations

import sqlite3
from pathlib import Path

_MAX_DISTINCT_FOR_ENUM = 25
_SAMPLE_EXAMPLES = 3

def _connect_ro(db_path: str) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)

def discover_schema(db_path: str) -> str:
    """Monta uma descricao textual do schema para o prompt do LLM."""
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Banco nao encontrado: {db_path}")

    conn = _connect_ro(db_path)
    try:
        cur = conn.cursor()
        tables = [
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]

        blocks: list[str] = []
        for table in tables:
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
    col_type = (col_type or "").upper()
    quoted = f'"{col}"'

    if any(t in col_type for t in ("INT", "REAL", "NUM", "FLOAT", "DOUBLE", "DEC")):
        row = cur.execute(
            f"SELECT MIN({quoted}), MAX({quoted}) FROM '{table}' "
            f"WHERE {quoted} IS NOT NULL"
        ).fetchone()
        if row and row[0] is not None:
            return f"  -> intervalo: {row[0]} a {row[1]}"
        return ""

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

