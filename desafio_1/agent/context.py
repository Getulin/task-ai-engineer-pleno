from __future__ import annotations

import re
import unicodedata

_DEPENDENT_START = re.compile(
    r"^(?:e\b|desses?\b|dessas?\b|del[ea]s?\b|iss[oa]\b|"
    r"ess[ea]s?\b|aquel[ea]s?\b)"
)
_FOLLOWUP_START = re.compile(r"^(?:agora\b|tambem\b|por\b|em\b|n[oa]s?\b|refaca\b|tente\b)")


def _normalize(question: str) -> str:
    normalized = unicodedata.normalize("NFD", question.casefold().strip())
    return "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )


def requires_context(question: str) -> bool:
    return bool(_DEPENDENT_START.match(_normalize(question)))


def is_followup(question: str) -> bool:
    normalized = _normalize(question)
    return requires_context(question) or bool(_FOLLOWUP_START.match(normalized))
