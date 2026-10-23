import json
import math
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import prompts
from agent.db import UnsafeQueryError, run_query
from agent.graph import build_agent
from agent.config import Settings
from agent.schema import discover_schema, find_partial_months

DB = ROOT.parent / "data" / "anexo_desafio_1.db"


def _rows(sql):
    with closing(sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)) as conn:
        return conn.execute(sql).fetchall()


MAY_APP_STATES = """
SELECT c.estado, COUNT(DISTINCT c.id) AS clientes
FROM clientes AS c
JOIN compras AS p ON p.cliente_id = c.id
WHERE p.canal = 'App' AND strftime('%m', p.data_compra) = '05'
GROUP BY c.estado
ORDER BY clientes DESC, c.estado
LIMIT 5
"""

WHATSAPP_2024 = """
SELECT COUNT(DISTINCT cliente_id) AS clientes
FROM campanhas_marketing
WHERE canal = 'WhatsApp' AND interagiu = 1
  AND data_envio >= '2024-01-01' AND data_envio < '2025-01-01'
"""

PURCHASES_PER_CUSTOMER = """
SELECT categoria, COUNT(*) AS compras, COUNT(DISTINCT cliente_id) AS clientes,
       1.0 * COUNT(*) / COUNT(DISTINCT cliente_id) AS media
FROM compras
GROUP BY categoria
ORDER BY media DESC, categoria
"""

UNRESOLVED_COMPLAINTS = """
SELECT canal, COUNT(*) AS reclamacoes
FROM suporte
WHERE tipo_contato = 'Reclamação' AND resolvido = 0
GROUP BY canal
ORDER BY canal
"""

COMPLAINT_TREND = """
SELECT strftime('%Y-%m', data_contato) AS mes, canal,
       COUNT(*) AS reclamacoes
FROM suporte
WHERE tipo_contato = 'Reclamação'
  AND data_contato >= '2024-08-01' AND data_contato < '2025-07-01'
GROUP BY mes, canal
ORDER BY mes, canal
"""

COMPLAINT_TREND_WITH_PARTIAL_MONTHS = """
SELECT strftime('%Y-%m', data_contato) AS mes, canal,
       COUNT(*) AS reclamacoes
FROM suporte
WHERE tipo_contato = 'Reclamação'
  AND data_contato > date((SELECT MAX(data_contato) FROM suporte), '-1 year')
GROUP BY mes, canal
ORDER BY mes, canal
"""


def test_top_five_states_count_people_in_app_purchases_in_may():
    expected = [
        ("São Paulo", 6),
        ("Minas Gerais", 3),
        ("Santa Catarina", 3),
        ("Alagoas", 2),
        ("Espírito Santo", 2),
    ]
    assert _rows(MAY_APP_STATES) == expected
    assert run_query(str(DB), MAY_APP_STATES).rows == expected


def test_whatsapp_campaigns_count_interacting_people_in_2024():
    assert _rows(WHATSAPP_2024) == [(17,)]
    assert run_query(str(DB), WHATSAPP_2024).rows == [(17,)]


def test_purchase_categories_rank_by_purchases_per_customer():
    expected = [
        ("Roupas", 157, 71),
        ("Viagens", 160, 74),
        ("Livros", 164, 83),
        ("Serviços", 155, 79),
        ("Eletrônicos", 150, 78),
        ("Alimentos", 160, 85),
    ]
    rows = _rows(PURCHASES_PER_CUSTOMER)
    assert [(category, purchases, customers) for category, purchases, customers, _ in rows] == expected
    assert run_query(str(DB), PURCHASES_PER_CUSTOMER).rows == rows
    for _, purchases, customers, average in rows:
        assert math.isclose(average, purchases / customers)


def test_unresolved_complaints_by_channel():
    expected = [("Chat", 18), ("E-mail", 14), ("Telefone", 19)]
    assert _rows(UNRESOLVED_COMPLAINTS) == expected
    assert run_query(str(DB), UNRESOLVED_COMPLAINTS).rows == expected


def test_complaint_trend_uses_complete_months_and_keeps_channel_series():
    rows = _rows(COMPLAINT_TREND)
    assert run_query(str(DB), COMPLAINT_TREND).rows == rows
    assert rows[0] == ("2024-08", "Chat", 2)
    assert rows[-1] == ("2025-06", "Telefone", 4)
    assert len({month for month, _, _ in rows}) == 11
    totals = {
        channel: sum(count for _, current, count in rows if current == channel)
        for channel in {channel for _, channel, _ in rows}
    }
    assert totals == {"Chat": 33, "E-mail": 24, "Telefone": 31}


def test_schema_reports_partial_months_at_data_boundaries():
    assert find_partial_months(str(DB)) == ["2024-07", "2025-07"]
    schema = discover_schema(str(DB))
    assert "meses parciais: 2024-07 (a partir do dia 23), 2025-07 (ate o dia 22)" in schema


@pytest.mark.parametrize("limit, expected_truncated", [(7, True), (100, False)])
def test_row_limit_reports_whether_result_is_partial(limit, expected_truncated):
    result = run_query(str(DB), "SELECT id FROM clientes ORDER BY id", row_limit=limit)
    assert result.row_count == min(limit, 100)
    assert result.truncated is expected_truncated


@pytest.mark.parametrize("limit", [0, -1])
def test_row_limit_must_be_positive(limit):
    with pytest.raises(ValueError):
        run_query(str(DB), "SELECT id FROM clientes", row_limit=limit)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM clientes; DELETE FROM clientes",
    "WITH wiped AS (DELETE FROM clientes RETURNING *) SELECT * FROM wiped",
    "PRAGMA writable_schema = 1",
])
def test_write_attempts_are_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        run_query(str(DB), sql)


def test_missing_table_raises_sql_error_for_agent_to_repair():
    with pytest.raises(sqlite3.Error):
        run_query(str(DB), "SELECT COUNT(*) FROM tabela_inexistente")


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = iter(replies)

    def invoke(self, messages):
        return next(self.replies)


class RecordingLLM(ScriptedLLM):
    def __init__(self, replies):
        super().__init__(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return super().invoke(messages)


def _settings():
    return Settings(
        provider="ollama", model="test", temperature=0, ollama_base_url="",
        db_path=str(DB), max_repair_attempts=3, row_limit=1000,
    )


def test_valid_but_incomplete_sql_is_revised_before_answering():
    llm = ScriptedLLM([
        "SELECT COUNT(*) AS clientes FROM campanhas_marketing",
        '{"sufficient": false, "feedback": "Faltam canal, interação e ano."}',
        WHATSAPP_2024,
        '{"sufficient": true, "feedback": ""}',
        '{"type": "table", "x": null, "y": null, "title": "Clientes"}',
        "17 clientes interagiram com campanhas de WhatsApp em 2024.",
    ])
    result = build_agent(_settings(), llm=llm).invoke({
        "question": "Quantos clientes interagiram com campanhas de WhatsApp em 2024?",
        "trace": [],
    })
    assert result["result_rows"] == [(17,)]
    assert result["sql"].strip() == WHATSAPP_2024.strip()
    assert [step["step"] for step in result["trace"]].count("executar_sql") == 2
    assert result["answer"].startswith("17 clientes")


def test_sql_execution_error_is_repaired_and_both_queries_are_visible():
    llm = ScriptedLLM([
        "SELECT COUNT(*) FROM tabela_inexistente",
        WHATSAPP_2024,
        '{"sufficient": true, "feedback": ""}',
        '{"type": "table", "x": null, "y": null, "title": "Clientes"}',
        "17 clientes.",
    ])
    result = build_agent(_settings(), llm=llm).invoke({
        "question": "Quantos clientes interagiram com campanhas de WhatsApp em 2024?",
        "trace": [],
    })
    assert result["result_rows"] == [(17,)]
    steps = [step["step"] for step in result["trace"]]
    assert "erro_execucao" in steps
    assert "executar_sql" in steps
    assert steps.count("gerar_sql") == 2


def test_failed_review_does_not_leave_previous_result_visible():
    llm = ScriptedLLM([
        "SELECT COUNT(*) AS clientes FROM clientes",
        '{"sufficient": false, "feedback": "A contagem não aplica os filtros pedidos."}',
        "SELECT * FROM tabela_inexistente",
        "SELECT * FROM tabela_inexistente",
        "SELECT * FROM tabela_inexistente",
    ])
    result = build_agent(_settings(), llm=llm).invoke({
        "question": "Quantos clientes interagiram com campanhas de WhatsApp em 2024?",
        "trace": [],
    })
    assert "falhou" in result["answer"]
    assert result["result_columns"] == []
    assert result["result_rows"] == []
    assert result["result_truncated"] is False


TABLE_VIZ = '{"type": "table", "x": null, "y": null, "series": null, "title": "Resultado"}'


def _ask(llm, question):
    return build_agent(_settings(), llm=llm).invoke({"question": question, "trace": []})


def test_ambiguous_question_is_answered_with_declared_assumption():
    assumption = "Não resolvidas são as reclamações com resolvido = 0."
    llm = ScriptedLLM([
        UNRESOLVED_COMPLAINTS,
        json.dumps({"verdict": "assumption", "feedback": "", "assumption": assumption}),
        TABLE_VIZ,
        "Considerei não resolvidas as reclamações com resolvido = 0.",
    ])
    result = _ask(llm, "Qual o numero de reclamacoes nao resolvidas por canal?")
    assert result["answer_status"] == "assumption"
    assert result["assumptions"] == [assumption]
    assert result["result_rows"] == [("Chat", 18), ("E-mail", 14), ("Telefone", 19)]
    assert [step["step"] for step in result["trace"]].count("executar_sql") == 1


def test_unresolved_review_keeps_last_result_and_reports_caveat():
    llm = ScriptedLLM([
        "SELECT COUNT(*) AS clientes FROM campanhas_marketing",
        '{"verdict": "revise", "feedback": "Faltam canal, interação e ano."}',
        WHATSAPP_2024,
        '{"verdict": "revise", "feedback": "Confirme se o ano usa a data de envio."}',
        TABLE_VIZ,
        "17 clientes, valor não confirmado.",
    ])
    result = _ask(llm, "Quantos clientes interagiram com campanhas de WhatsApp em 2024?")
    assert result["result_rows"] == [(17,)]
    assert result["answer_status"] == "unconfirmed"
    assert result["caveat"] == "Confirme se o ano usa a data de envio."
    assert result["answer"] == "17 clientes, valor não confirmado."
    assert len(result["review_history"]) == 2


def test_second_verification_receives_previous_feedback():
    feedback = "O terceiro mês deve ser contado como M+2."
    llm = RecordingLLM([
        "SELECT COUNT(*) AS clientes FROM clientes",
        json.dumps({"verdict": "revise", "feedback": feedback}),
        "SELECT COUNT(DISTINCT cliente_id) AS clientes FROM compras",
        '{"verdict": "ok", "feedback": ""}',
        TABLE_VIZ,
        "100 clientes.",
    ])
    result = _ask(llm, "Quantos clientes compraram?")
    assess_calls = [m for m in llm.calls if m[0].content == prompts.ASSESS_SYSTEM]
    assert len(assess_calls) == 2
    assert "Revisões anteriores: nenhuma" in assess_calls[0][1].content
    assert feedback in assess_calls[1][1].content
    assert result["answer_status"] == "confirmed"


def test_verifier_failure_marks_answer_as_unverified():
    llm = ScriptedLLM([WHATSAPP_2024, "sem json", TABLE_VIZ, "17 clientes."])
    result = _ask(llm, "Quantos clientes interagiram com campanhas de WhatsApp em 2024?")
    assert result["answer_status"] == "unverified"
    assert result["result_rows"] == [(17,)]


def test_result_with_partial_months_carries_a_data_note():
    llm = ScriptedLLM([
        COMPLAINT_TREND_WITH_PARTIAL_MONTHS,
        '{"verdict": "ok", "feedback": ""}',
        TABLE_VIZ,
        "Tendência mensal.",
    ])
    result = _ask(llm, "Qual a tendência de reclamações por canal no último ano?")
    assert len(result["data_notes"]) == 1
    assert "2024-07, 2025-07" in result["data_notes"][0]


def test_result_with_complete_months_has_no_data_note():
    llm = ScriptedLLM([COMPLAINT_TREND, '{"verdict": "ok", "feedback": ""}', TABLE_VIZ, "Tendência."])
    result = _ask(llm, "Qual a tendência de reclamações por canal no último ano?")
    assert result["data_notes"] == []


def test_multi_channel_trend_keeps_series_when_viz_model_fails():
    llm = ScriptedLLM([
        COMPLAINT_TREND,
        '{"sufficient": true, "feedback": ""}',
        "not json",
        "Tendência mensal de reclamações por canal.",
    ])
    result = build_agent(_settings(), llm=llm).invoke({
        "question": "Qual a tendência de reclamações por canal no último ano?",
        "trace": [],
    })
    assert result["viz"]["type"] == "line"
    assert result["viz"]["x"] == "mes"
    assert result["viz"]["y"] == "reclamacoes"
    assert result["viz"]["series"] == "canal"
    assert len(result["result_rows"]) > 12
