from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlglot import exp, parse_one

_COUNT = re.compile(r"\b(?:quant[oa]s?|n[uú]mero de|total de)\b")
_RANK = re.compile(r"\b(?:maior|menor|top|ranking|mais(?!\s+de\b)|menos(?!\s+de\b))\b")
_TREND = re.compile(r"\b(?:tend[eê]ncia|evolu[cç][aã]o|ao longo|m[eê]s a m[eê]s)\b")
_DIMENSION = re.compile(r"\bpor\s+(?:cada\s+)?(canal|estado|categoria|campanha|mes|ano|genero|produto)\b")
_PERIOD = re.compile(r"^\d{4}-(?:\d{2})(?:-\d{2})?$")
_DATE = re.compile(r"\b(?:\d{4}-\d{2}(?:-\d{2})?|\d{2}/\d{4}|\d{2}/\d{2}/\d{4})\b")
_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])")


def _plain(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _date_key(value: str) -> str:
    if "/" not in value:
        return value
    parts = value.split("/")
    return f"{parts[2]}-{parts[1]}-{parts[0]}" if len(parts) == 3 else f"{parts[1]}-{parts[0]}"


def _number_value(token: str) -> Decimal:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", token):
        token = token.replace(".", "").replace(",", ".")
    elif "," in token:
        token = token.replace(",", ".")
    return Decimal(token)


def _grouped_dimensions(query: exp.Expression) -> str:
    terms: list[str] = []
    for select in query.find_all(exp.Select):
        group = select.args.get("group")
        if not group:
            continue
        projections = select.expressions
        aliases = {item.alias: item for item in projections if item.alias}
        for item in group.expressions:
            target = item
            if isinstance(item, exp.Literal) and item.is_int:
                index = int(item.this) - 1
                if 0 <= index < len(projections):
                    target = projections[index]
            elif isinstance(item, exp.Column) and not item.table and item.name in aliases:
                target = aliases[item.name]
            terms.append(_plain(target.sql(dialect="sqlite")))
    return " ".join(terms)


def evidence_issues(
    question: str, sql: str, columns: list[str], rows: list[tuple], truncated: bool
) -> list[str]:
    """Rejeita incompatibilidades objetivas entre pergunta, SQL e resultado."""
    issues: list[str] = []
    if truncated:
        issues.append("O resultado foi cortado pelo limite de linhas; agregue ou restrinja a consulta.")
    if not columns:
        return [*issues, "A consulta não retornou colunas para sustentar uma resposta."]
    if not rows:
        return issues

    query = parse_one(sql, read="sqlite")
    asked = _plain(question)
    numeric = any(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for row in rows for value in row
    )
    aggregate = any(query.find_all(exp.AggFunc))
    grouped = bool(query.find(exp.Group) or query.find(exp.Window))

    if _COUNT.search(asked) and (not aggregate or not numeric):
        issues.append("A pergunta pede uma contagem ou total, mas falta uma medida agregada numérica.")
    dimensions = set(_DIMENSION.findall(asked))
    group_terms = _grouped_dimensions(query)
    for dimension in sorted(dimensions):
        if dimension not in group_terms:
            issues.append(f"A pergunta pede resultados por {dimension}, mas o SQL não agrupa por essa dimensão.")
    if _RANK.search(asked) and not numeric:
        issues.append("A comparação pede a medida numérica usada para identificar o resultado.")
    if _RANK.search(asked) and not query.find(exp.Order):
        issues.append("A comparação exige ordenar a consulta pela medida relevante.")
    if _TREND.search(asked):
        periods = {
            value for row in rows for value in row
            if isinstance(value, str) and _PERIOD.fullmatch(value)
        }
        if not aggregate or not grouped or len(periods) < 2:
            issues.append("A tendência exige uma medida por pelo menos dois períodos agrupados.")
    return issues


def unsupported_numbers(
    answer: str, question: str, sql: str, rows: list[tuple], notes: list[str] | None = None
) -> list[str]:
    """Confere números do texto contra medidas retornadas e períodos da consulta."""
    measures = [
        Decimal(str(value))
        for row in rows for value in row
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    period_count = len({
        value for row in rows for value in row
        if isinstance(value, str) and _PERIOD.fullmatch(value)
    })
    window_months = {
        int(value) for value in re.findall(r"['\"]-?(\d+)\s+months?['\"]", sql, re.IGNORECASE)
    }
    context = f"{question} {sql} {' '.join(notes or [])} " + " ".join(
        value for row in rows for value in row if isinstance(value, str)
    )
    dates = {_date_key(value) for value in _DATE.findall(context)}
    for end in re.findall(r"<\s*['\"](\d{4}-\d{2}-\d{2})['\"]", sql):
        try:
            dates.add((date.fromisoformat(end) - timedelta(days=1)).isoformat())
        except ValueError:
            pass
    unsupported: list[str] = []
    remaining = answer
    for match in reversed(list(_DATE.finditer(answer))):
        token = match.group()
        if _date_key(token) not in dates:
            unsupported.append(token)
        remaining = remaining[:match.start()] + " " * len(token) + remaining[match.end():]

    for match in _NUMBER.finditer(remaining):
        token = match.group()
        if token.isdigit() and len(token) == 4 and token in context:
            continue
        following = _plain(remaining[match.end():match.end() + 24])
        last_year_window = bool(re.search(r"\bultim\w*\s+ano\b", _plain(question)))
        if token.isdigit() and (
            (int(token) == period_count and re.match(r"\s+(?:meses?|periodos?)\b", following))
            or (int(token) in window_months and re.match(r"\s+meses?\b", following))
            or (
                int(token) == 12 and last_year_window
                and re.match(r"\s+meses?\b", following)
                and not re.search(r"\bcompletos?\b", following)
            )
            or (int(token) == len(rows) and re.match(r"\s+(?:linhas?|registros?)\b", following))
        ):
            continue
        before = remaining[max(0, match.start() - 80):match.start()]
        filter_match = re.search(r"([a-zA-Z_][\w.]*)\s*(=|>=|<=|>|<)\s*$", before)
        if filter_match:
            column, operator = filter_match.groups()
            if re.search(
                rf"\b{re.escape(column)}\s*{re.escape(operator)}\s*{re.escape(token)}\b",
                sql, re.IGNORECASE,
            ):
                continue
        try:
            claimed = _number_value(token)
            precision = Decimal(1).scaleb(claimed.as_tuple().exponent)
            if any(
                value.quantize(precision, rounding=ROUND_HALF_UP) == claimed
                for value in measures
            ):
                continue
        except (InvalidOperation, ValueError):
            pass
        unsupported.append(token)
    return sorted(set(unsupported))


def missing_rank_label(question: str, answer: str, rows: list[tuple]) -> bool:
    """Uma resposta sobre o líder deve citar o valor retornado para esse líder."""
    return bool(
        _RANK.search(_plain(question))
        and len(rows) == 1
        and rows[0]
        and isinstance(rows[0][0], str)
        and _plain(rows[0][0]) not in _plain(answer)
    )


def mismatched_category_values(answer: str, rows: list[tuple]) -> list[str]:
    """Confere pares categoria-medida quando o resultado tem duas colunas."""
    if not rows or len(rows) > 50 or any(
        len(row) != 2 or not isinstance(row[0], str)
        or _PERIOD.fullmatch(row[0])
        or not isinstance(row[1], (int, float)) or isinstance(row[1], bool)
        for row in rows
    ):
        return []

    normalized = _plain(answer)
    candidates = []
    for label, value in rows:
        for match in re.finditer(rf"(?<!\w){re.escape(_plain(label))}(?!\w)", normalized):
            candidates.append((match.start(), match.end(), label, Decimal(str(value))))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    occurrences = []
    for item in candidates:
        if not occurrences or item[0] >= occurrences[-1][1]:
            occurrences.append(item)

    mismatches = []
    for index, (_, end, label, expected) in enumerate(occurrences):
        next_start = occurrences[index + 1][0] if index + 1 < len(occurrences) else len(normalized)
        segment = _DATE.sub(" ", normalized[end:next_start])
        for match in _NUMBER.finditer(segment):
            token = match.group()
            if token.isdigit() and len(token) == 4 and 1900 <= int(token) <= 2100:
                if expected != int(token):
                    continue
            try:
                claimed = _number_value(token)
                precision = Decimal(1).scaleb(claimed.as_tuple().exponent)
                if expected.quantize(precision, rounding=ROUND_HALF_UP) != claimed:
                    mismatches.append(label)
            except (InvalidOperation, ValueError):
                mismatches.append(label)
            break
    return sorted(set(mismatches))
