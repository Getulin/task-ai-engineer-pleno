from pathlib import Path
from types import SimpleNamespace

from desafio_1.agent.config import Settings
from desafio_1.agent.graph import build_agent

DB = Path(__file__).resolve().parents[2] / "data" / "anexo_desafio_1.db"


class UsageLLM:
    def __init__(self, replies):
        self.replies = iter(replies)

    def invoke(self, messages):
        return SimpleNamespace(
            content=next(self.replies),
            usage_metadata={"input_tokens": 100, "output_tokens": 20},
        )


def ask(max_calls=12, max_cost=0):
    settings = Settings(
        provider="ollama", model="test", temperature=0, ollama_base_url="",
        db_path=str(DB), max_repair_attempts=3, row_limit=1000,
        max_model_calls=max_calls, input_usd_per_million=1,
        output_usd_per_million=2, max_estimated_cost_usd=max_cost,
    )
    llm = UsageLLM([
        "SELECT COUNT(*) AS clientes FROM clientes",
        '{"verdict":"ok","feedback":""}',
        '{"type":"table","x":null,"y":null,"title":"Clientes"}',
        "100 clientes.",
    ])
    return build_agent(settings, llm=llm).invoke({
        "question": "Quantos clientes existem?", "trace": [],
    })


def test_model_usage_is_recorded_without_prompts_or_rows():
    result = ask()
    calls = [step["data"] for step in result["trace"] if step["step"] == "chamada_modelo"]
    assert len(calls) == 4
    assert sum(call["input_tokens"] for call in calls) == 400
    assert sum(call["output_tokens"] for call in calls) == 80
    assert sum(call["estimated_cost_usd"] for call in calls) == 0.00056
    assert all("prompt" not in call and "rows" not in call for call in calls)
    assert result["answer_status"] == "confirmed"


def test_model_call_limit_stops_final_synthesis():
    result = ask(max_calls=2)
    assert result["answer_status"] == "unconfirmed"
    assert "limite de recursos" in result["answer"].lower()
    assert len([step for step in result["trace"] if step["step"] == "chamada_modelo"]) == 2


def test_estimated_cost_limit_stops_next_call():
    result = ask(max_cost=0.0001)
    assert result["answer_status"] == "unconfirmed"
    assert len([step for step in result["trace"] if step["step"] == "chamada_modelo"]) == 1
    assert "custo" in result["caveat"]
