from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from sqlglot import exp, parse_one

_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
_MONTH_RANGE = re.compile(
    r"\b(?:de|entre)\s+(" + "|".join(_MONTHS) + r")\s+(?:a|ate|e)\s+("
    + "|".join(_MONTHS) + r")\s+de\s+((?:19|20)\d{2})\b"
)


def _plain(value: str) -> str:
    text = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


@dataclass(frozen=True)
class QueryPlan:
    tables: tuple[str, ...]
    date_columns: tuple[str, ...]
    filters: tuple[tuple[str, str], ...]
    distinct_clients: bool
    top_n: int | None
    exclude_partial_months: bool
    expected_months: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


def make_plan(question: str) -> QueryPlan:
    """Extrai apenas obrigações explícitas e de alta confiança da pergunta."""
    text = _plain(question)
    purchase = bool(re.search(r"\b(?:compr\w*|pagament\w*)\b", text))
    campaign = bool(re.search(r"\bcampanh\w*\b", text))
    support = bool(re.search(r"\b(?:reclam\w*|suport\w*|contat\w*)\b", text))
    temporal = bool(re.search(
        r"\b(?:20\d{2}|19\d{2}|janeiro|fevereiro|marco|abril|maio|junho|julho|"
        r"agosto|setembro|outubro|novembro|dezembro|ultim\w*\s+ano)\b", text
    ))
    tables = []
    dates = []
    filters = []
    for found, table, column in (
        (purchase, "compras", "data_compra"),
        (campaign, "campanhas_marketing", "data_envio"),
        (support, "suporte", "data_contato"),
    ):
        if found:
            tables.append(table)
            if temporal:
                dates.append(column)
    if purchase and re.search(r"\b(?:via|pelo|pela|no)\s+app\b", text):
        filters.append(("compras.canal", "App"))
    if campaign and re.search(r"\bwhatsapp\b", text):
        filters.append(("campanhas_marketing.canal", "WhatsApp"))
    if campaign and (
        "adesao" in text
        or re.search(r"\bclientes?\s+(?:que\s+)?interag\w*\b", text)
    ):
        filters.append(("campanhas_marketing.interagiu", "1"))
    if "reclam" in text:
        filters.append(("suporte.tipo_contato", "Reclamação"))
        if re.search(r"\bnao\s+resolvid\w*\b", text):
            filters.append(("suporte.resolvido", "0"))
    top = re.search(r"\b(?:top\s*|(?:liste\s+)?os\s+)(\d+)\s+(?:estados|campanhas|categorias|canais)\b", text)
    trend = bool(re.search(r"\b(?:tendencia|evolucao|serie\s+mensal|coorte\w*)\b", text))
    include_partial = bool(re.search(r"\b(?:inclu\w*|com)\s+(?:os\s+)?meses\s+(?:parciais|incompletos)\b", text))
    month_range = _MONTH_RANGE.search(text)
    monthly_groups = bool(re.search(r"\b(?:cada\s+mes|coorte\w*|serie\s+mensal|tendencia)\b", text))
    expected_months: tuple[str, ...] = ()
    if month_range and monthly_groups:
        first, last, year = month_range.groups()
        if _MONTHS[first] <= _MONTHS[last]:
            expected_months = tuple(
                f"{year}-{month:02d}" for month in range(_MONTHS[first], _MONTHS[last] + 1)
            )
    distinct_clients = bool(
        re.search(r"\bclientes?\b", text)
        and (purchase or campaign or support)
        and not re.search(r"\b(?:nunca|sem|media\s+(?:de\s+)?\w+\s+por\s+cliente)\b", text)
    )
    return QueryPlan(
        tuple(tables), tuple(dates), tuple(filters), distinct_clients,
        int(top.group(1)) if top else None, trend and not include_partial,
        expected_months,
    )


def _table_aliases(query: exp.Expression) -> dict[str, str]:
    return {table.alias_or_name.lower(): table.name.lower() for table in query.find_all(exp.Table)}


def _has_filter(query: exp.Expression, aliases: dict[str, str], target: str, value: str) -> bool:
    table, name = target.split(".")
    for comparison in query.find_all(exp.EQ):
        left, right = comparison.this, comparison.expression
        if isinstance(right, exp.Column) and isinstance(left, exp.Literal):
            left, right = right, left
        if not isinstance(left, exp.Column) or not isinstance(right, exp.Literal):
            continue
        if left.name.lower() != name or (left.table and aliases.get(left.table.lower()) != table):
            continue
        if _plain(str(right.this)) == _plain(value):
            return True
    return False


def _counts_unique_clients(query: exp.Expression, aliases: dict[str, str]) -> bool:
    for count in query.find_all(exp.Count):
        if not isinstance(count.this, exp.Distinct):
            continue
        for column in count.find_all(exp.Column):
            if column.name.lower() == "cliente_id":
                return True
            if column.name.lower() == "id" and aliases.get(column.table.lower()) == "clientes":
                return True
    for select in query.find_all(exp.Select):
        group = select.args.get("group")
        if group and any(column.name.lower() == "cliente_id" for column in group.find_all(exp.Column)):
            return True
        if select.args.get("distinct") and any(
            column.name.lower() == "cliente_id" for column in select.find_all(exp.Column)
        ):
            return True
    return False


def plan_issues(plan: QueryPlan, sql: str, rows: list[tuple], partial_months: list[str]) -> list[str]:
    query = parse_one(sql, read="sqlite")
    aliases = _table_aliases(query)
    tables = set(aliases.values())
    issues = []
    for table in plan.tables:
        if table not in tables:
            issues.append(f"A pergunta exige a tabela {table}.")
    columns = {column.name.lower() for column in query.find_all(exp.Column)}
    for column in plan.date_columns:
        if column not in columns:
            issues.append(f"O período deve usar a data do evento em {column}.")
    for target, value in plan.filters:
        if target.split(".")[0] in tables and not _has_filter(query, aliases, target, value):
            issues.append(f"Falta filtrar {target} pelo valor {value!r}.")
    if plan.distinct_clients and any(query.find_all(exp.Count)) and not _counts_unique_clients(query, aliases):
        # Counting rows from clientes without a JOIN may be valid for a NOT EXISTS question.
        if not (tables == {"clientes"} or ("clientes" in tables and query.find(exp.Exists))):
            issues.append("A pergunta pede clientes distintos, não número de eventos.")
    if plan.top_n and len(rows) == plan.top_n:
        order = query.find(exp.Order)
        if not order or len(order.expressions) < 2:
            issues.append("O ranking precisa de desempate determinístico após a medida.")
    if plan.exclude_partial_months:
        included = sorted({value for row in rows for value in row
                           if isinstance(value, str) and value in partial_months})
        if included:
            issues.append("A série inclui meses parciais: " + ", ".join(included) + ".")
    if plan.expected_months:
        returned = {value for row in rows for value in row if isinstance(value, str)}
        required = set(plan.expected_months) - (set(partial_months) if plan.exclude_partial_months else set())
        missing = sorted(required - returned)
        if missing:
            issues.append("Faltam períodos solicitados: " + ", ".join(missing) + ".")
    return issues
