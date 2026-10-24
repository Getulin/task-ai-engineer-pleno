from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
_MONTH_PATTERN = re.compile(r"\b(" + "|".join(_MONTHS) + r")s?\b")
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
_EVENT_PATTERN = re.compile(
    r"\b(?:compr\w*|pag\w*|vend\w*|campanh\w*|interag\w*|"
    r"reclam\w*|contat\w*|suport\w*|atend\w*|envi\w*|receb\w*|"
    r"acess\w*|pedid\w*)\b"
)
_REGISTRATION_PATTERN = re.compile(r"\b(?:cadastr\w*|registr\w*|inscri\w*)\b")
_RELATIVE_PERIOD_PATTERN = re.compile(
    r"\bultim\w*\s+(?:(?:\d+|dois|tres)\s+)?anos?\b"
)


@dataclass(frozen=True)
class TemporalInterpretation:
    guidance: str
    assumption: str | None = None
    clarification: str | None = None


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in value if unicodedata.category(char) != "Mn")


def _asks_latest_month(normalized: str, match: re.Match) -> bool:
    before = normalized[max(0, match.start() - 28):match.start()]
    after = normalized[match.end():match.end() + 28]
    return bool(
        re.search(r"(?:ultim[oa]\s+(?:mes\s+de\s+)?|mais\s+recente\s+|ultima\s+ocorrencia\s+de\s+)$", before)
        or re.match(r"\s+(?:mais\s+recente|do\s+ultimo\s+ano)\b", after)
    )


def interpret_question(question: str) -> TemporalInterpretation:
    """Define o alcance de meses nomeados antes de gerar ou verificar o SQL."""
    normalized = _normalize(question)
    matches = list(_MONTH_PATTERN.finditer(normalized))
    if not matches:
        return TemporalInterpretation("Nenhum mes do calendario foi citado pelo nome.")

    months = sorted({_MONTHS[match.group(1)] for match in matches})
    labels = ", ".join(f"{month:02d}" for month in months)
    years = sorted(set(_YEAR_PATTERN.findall(normalized)))
    latest = any(_asks_latest_month(normalized, match) for match in matches)
    relative_period = bool(_RELATIVE_PERIOD_PATTERN.search(normalized))

    if years:
        guidance = (
            f"Mes(es) citado(s): {labels}; ano(s) explicito(s): {', '.join(years)}. "
            "Use apenas os periodos pedidos e a data do evento correspondente."
        )
        assumption = None
    elif latest:
        guidance = (
            f"Mes(es) citado(s): {labels}; o usuario pediu a ocorrencia mais recente. "
            "Encontre o ano mais recente desse mes na coluna de data do evento, "
            "sem usar a data atual."
        )
        assumption = "Considerei a ocorrência mais recente do mês citado nos dados."
    elif relative_period:
        guidance = (
            f"Mes(es) citado(s): {labels}; aplique tambem o periodo relativo "
            "pedido pelo usuario, ancorado na maior data da tabela do evento. "
            "Nao use a data atual nem reduza o periodo a uma unica ocorrencia."
        )
        assumption = None
    else:
        guidance = (
            f"Mes(es) citado(s): {labels}; nenhum ano foi especificado. "
            "Inclua TODAS as ocorrencias desses meses em todos os anos disponiveis "
            "na coluna de data do evento. Nao fixe um ano nem troque a data do evento."
        )
        assumption = (
            "Considerei todas as ocorrências dos meses citados, em todos os anos disponíveis."
            if len(months) > 1 else
            "Considerei todas as ocorrências do mês citado, em todos os anos disponíveis."
        )

    if re.search(r"\bclientes?\b", normalized):
        if _REGISTRATION_PATTERN.search(normalized):
            return TemporalInterpretation(
                guidance, clarification=(
                    "O banco não tem data de cadastro dos clientes. Qual evento deseja "
                    "usar para definir os clientes desse mês: compra, interação com "
                    "campanha ou contato com o suporte?"
                ),
            )
        if not _EVENT_PATTERN.search(normalized):
            return TemporalInterpretation(
                guidance, clarification=(
                    "Qual evento define 'clientes no mês' nesta pergunta: compra, "
                    "interação com campanha ou contato com o suporte? Informe também "
                    "o ano se quiser uma ocorrência específica."
                ),
            )

    return TemporalInterpretation(guidance, assumption)
