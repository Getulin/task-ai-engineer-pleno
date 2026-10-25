from __future__ import annotations

import sqlite3
from pathlib import Path

from .query_plan import QueryPlan

_CATEGORIES = {
    "compras": {"canal"},
    "campanhas_marketing": {"canal", "interagiu"},
    "suporte": {"tipo_contato", "resolvido"},
}
_DATES = {
    "compras": "data_compra",
    "campanhas_marketing": "data_envio",
    "suporte": "data_contato",
}


def inspect_relevant_values(db_path: str, plan: QueryPlan) -> dict:
    """Consulta somente categorias e datas dos eventos citados, sem dados individuais."""
    result: dict[str, dict] = {"categories": {}, "dates": {}}
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1) as connection:
        connection.execute("PRAGMA query_only=ON")
        for table in plan.tables:
            if table not in _DATES:
                continue
            date_column = _DATES[table]
            first, last = connection.execute(
                f'SELECT MIN("{date_column}"),MAX("{date_column}") FROM "{table}"'
            ).fetchone()
            result["dates"][f"{table}.{date_column}"] = {"first": first, "last": last}
            for column in sorted(_CATEGORIES[table]):
                values = connection.execute(
                    f'SELECT DISTINCT "{column}" FROM "{table}" '
                    f'WHERE "{column}" IS NOT NULL ORDER BY "{column}" LIMIT 26'
                ).fetchall()
                result["categories"][f"{table}.{column}"] = [row[0] for row in values]
    return result
