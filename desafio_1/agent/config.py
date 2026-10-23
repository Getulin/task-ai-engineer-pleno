from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=False)

@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    temperature: float
    ollama_base_url: str
    db_path: str
    max_repair_attempts: int
    row_limit: int

    @property
    def db_abspath(self) -> str:
        p = Path(self.db_path)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        return str(p)

def get_settings() -> Settings:
    """Le as configuracoes do ambiente, com defaults seguros (Ollama local)."""
    return Settings(
        provider=os.getenv("LLM_PROVIDER", "ollama").strip().lower(),
        model=os.getenv("LLM_MODEL", "qwen2.5-coder:7b").strip(),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
        db_path=os.getenv("DB_PATH", "data/anexo_desafio_1.db").strip(),
        max_repair_attempts=int(os.getenv("SQL_MAX_REPAIR_ATTEMPTS", "3")),
        row_limit=int(os.getenv("SQL_ROW_LIMIT", "1000")),
    )

