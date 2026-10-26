import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import prompts
from agent.config import Settings
from agent.context import is_followup
from agent.graph import build_agent

DB = ROOT.parent / "data" / "anexo_desafio_1.db"


class RecordingLLM:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return next(self.replies)


def _agent(llm):
    settings = Settings(
        provider="ollama", model="test", temperature=0, ollama_base_url="",
        db_path=str(DB), max_repair_attempts=3, row_limit=1000,
    )
    return build_agent(settings, llm=llm)


def test_followup_uses_previous_question_for_sql_and_shows_interpretation():
    previous = "Quantos clientes distintos compraram pelo App em setembro?"
    resolved = "Quantos clientes distintos compraram pelo App em setembro, por estado?"
    sql = """SELECT c.estado, COUNT(DISTINCT p.cliente_id) AS clientes
FROM clientes c JOIN compras p ON p.cliente_id = c.id
WHERE p.canal = 'App' AND strftime('%m', p.data_compra) = '09'
GROUP BY c.estado ORDER BY c.estado"""
    llm = RecordingLLM([
        json.dumps({"question": resolved}),
        sql,
        '{"verdict": "ok", "feedback": ""}',
        '{"type": "bar", "x": "estado", "y": "clientes", "series": null, "title": "Clientes por estado"}',
        "Clientes por estado.",
    ])
    result = _agent(llm).invoke({
        "question": "e por estado?", "previous_question": previous, "trace": [],
    })
    assert result["question"] == resolved
    assert result["original_question"] == "e por estado?"
    assert sum(row[1] for row in result["result_rows"]) == 22
    assert result["answer_status"] == "confirmed"
    assert result["trace"][0]["data"]["stage"] == "contexto"
    assert any(step["step"] == "contextualizar_pergunta" for step in result["trace"])
    assert llm.calls[0][0].content == prompts.CONTEXT_SYSTEM
    assert previous in llm.calls[0][1].content
    assert "result_rows" not in llm.calls[0][1].content


def test_independent_question_does_not_call_context_model():
    sql = "SELECT COUNT(DISTINCT cliente_id) FROM campanhas_marketing WHERE interagiu = 1"
    llm = RecordingLLM([
        sql,
        '{"verdict": "ok", "feedback": ""}',
        '{"type": "table", "x": null, "y": null, "series": null, "title": "Clientes"}',
        "Clientes que interagiram.",
    ])
    result = _agent(llm).invoke({
        "question": "Quantos clientes interagiram com campanhas?",
        "previous_question": "Quantos compraram pelo App em setembro?",
        "trace": [],
    })
    assert result["question"] == result["original_question"]
    assert llm.calls[0][0].content.startswith("Voce e um analista de dados")


def test_dependent_question_without_history_requests_clarification():
    llm = RecordingLLM([])
    result = _agent(llm).invoke({"question": "e por estado?", "trace": []})
    assert "depende de uma anterior" in result["answer"]
    assert not result.get("sql")
    assert llm.calls == []


def test_invalid_context_response_requests_complete_question():
    llm = RecordingLLM(["resposta fora do formato"])
    result = _agent(llm).invoke({
        "question": "e por estado?", "previous_question": "Quantos compraram?", "trace": [],
    })
    assert "pergunta completa" in result["answer"]
    assert not result.get("sql")


def test_followup_detection_distinguishes_complete_questions():
    assert is_followup("e por estado?")
    assert is_followup("em agosto?")
    assert not is_followup("Mostre o primeiro cliente.")
    assert not is_followup("Quantos clientes compraram pelo App em setembro?")
