import math
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.db import UnsafeQueryError, run_query
from agent.graph import build_agent
from agent.config import Settings

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


def test_complaint_trend_uses_latest_data_date_and_keeps_channel_series():
    rows = _rows(COMPLAINT_TREND)
    assert run_query(str(DB), COMPLAINT_TREND).rows == rows
    assert rows[0] == ("2024-07", "E-mail", 1)
    assert rows[-1] == ("2025-07", "Telefone", 2)
    assert len({month for month, _, _ in rows}) == 13
    totals = {
        channel: sum(count for _, current, count in rows if current == channel)
        for channel in {channel for _, channel, _ in rows}
    }
    assert totals == {"Chat": 34, "E-mail": 28, "Telefone": 35}


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
