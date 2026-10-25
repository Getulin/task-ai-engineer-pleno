from pathlib import Path

from desafio_1.agent.config import Settings
from desafio_1.agent.graph import build_agent
from desafio_1.agent.investigation import inspect_relevant_values
from desafio_1.agent.query_plan import make_plan

DB = Path(__file__).resolve().parents[2] / "data" / "anexo_desafio_1.db"


class RecordingLLM:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return next(self.replies)


def test_targeted_investigation_exposes_only_business_categories_and_dates():
    plan = make_plan("Quantos clientes interagiram com campanhas de WhatsApp em 2024?")
    data = inspect_relevant_values(str(DB), plan)
    assert "WhatsApp" in data["categories"]["campanhas_marketing.canal"]
    assert data["dates"]["campanhas_marketing.data_envio"]["first"]
    assert "nome" not in str(data).lower()
    assert "email" not in str(data).lower()


def test_empty_result_triggers_one_investigation_before_retry():
    llm = RecordingLLM([
        "SELECT COUNT(DISTINCT cliente_id) FROM campanhas_marketing WHERE canal='whatsapp'",
        """SELECT COUNT(DISTINCT cliente_id) AS clientes FROM campanhas_marketing
            WHERE canal='WhatsApp' AND interagiu=1 AND data_envio>='2024-01-01'
            AND data_envio<'2025-01-01'""",
        '{"verdict":"ok","feedback":""}',
        '{"type":"table","x":null,"y":null,"title":"Clientes"}',
        "17 clientes.",
    ])
    settings = Settings(
        provider="ollama", model="test", temperature=0, ollama_base_url="",
        db_path=str(DB), max_repair_attempts=3, row_limit=1000,
    )
    result = build_agent(settings, llm=llm).invoke({
        "question": "Quantos clientes interagiram com campanhas de WhatsApp em 2024?",
        "trace": [],
    })
    assert result["answer_status"] == "confirmed"
    assert result["result_rows"] == [(17,)]
    assert result["investigation_count"] == 1
    assert [step["step"] for step in result["trace"]].count("investigar_dados") == 1
    assert "WhatsApp" in llm.calls[1][1].content
