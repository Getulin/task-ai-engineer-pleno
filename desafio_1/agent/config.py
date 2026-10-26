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
    sql_timeout_s: float = 10.0
    requests_per_second: float = 0.0
    max_model_calls: int = 12
    input_usd_per_million: float = 0.0
    output_usd_per_million: float = 0.0
    max_estimated_cost_usd: float = 0.0

    @property
    def db_abspath(self) -> str:
        p = Path(self.db_path)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        return str(p)

def get_settings() -> Settings:
    """Le as configuracoes do ambiente; provedor e modelo sao obrigatorios."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    model = os.getenv("LLM_MODEL", "").strip()
    if not provider:
        raise RuntimeError(
            "Defina LLM_PROVIDER no .env (ollama | gemini | openai | groq). "
            "Veja o README para a configuração de cada provedor."
        )
    if not model:
        raise RuntimeError(
            "Defina LLM_MODEL no .env com um modelo do provedor escolhido."
        )
    max_model_calls = int(os.getenv("LLM_MAX_CALLS_PER_QUESTION", "12"))
    if max_model_calls < 1:
        raise ValueError("LLM_MAX_CALLS_PER_QUESTION deve ser positivo.")
    input_price = float(os.getenv("LLM_INPUT_USD_PER_MILLION", "0"))
    output_price = float(os.getenv("LLM_OUTPUT_USD_PER_MILLION", "0"))
    cost_limit = float(os.getenv("LLM_MAX_ESTIMATED_COST_USD", "0"))
    if min(input_price, output_price, cost_limit) < 0:
        raise ValueError("Preços e limite estimado de custo não podem ser negativos.")
    if cost_limit and not (input_price or output_price):
        raise ValueError("Configure os preços por milhão de tokens para limitar custo estimado.")
    return Settings(
        provider=provider,
        model=model,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
        db_path=os.getenv("DB_PATH", "data/anexo_desafio_1.db").strip(),
        max_repair_attempts=int(os.getenv("SQL_MAX_REPAIR_ATTEMPTS", "3")),
        row_limit=int(os.getenv("SQL_ROW_LIMIT", "1000")),
        sql_timeout_s=float(os.getenv("SQL_TIMEOUT_SECONDS", "10")),
        requests_per_second=float(os.getenv("LLM_REQUESTS_PER_SECOND", "0")),
        max_model_calls=max_model_calls,
        input_usd_per_million=input_price,
        output_usd_per_million=output_price,
        max_estimated_cost_usd=cost_limit,
    )

