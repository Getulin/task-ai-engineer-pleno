from pathlib import Path

import pytest

from desafio_1.agent.config import Settings
from desafio_1.agent.db import UnsafeQueryError, run_query, validate_read_only
from desafio_1.agent.evidence import (
    evidence_issues, mismatched_category_values, missing_rank_label, unsupported_numbers,
)
from desafio_1.agent.graph import build_agent

DB = Path(__file__).resolve().parents[2] / "data" / "anexo_desafio_1.db"


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = iter(replies)

    def invoke(self, messages):
        return next(self.replies)


def settings():
    return Settings(
        provider="ollama", model="test", temperature=0, ollama_base_url="",
        db_path=str(DB), max_repair_attempts=3, row_limit=1000,
    )


@pytest.mark.parametrize("sql", [
    "SELECT 1; DELETE FROM clientes",
    "WITH dados AS (DELETE FROM clientes RETURNING id) SELECT * FROM dados",
    "SELECT load_extension('x')",
    "SELECT * FROM outro.clientes",
    "PRAGMA table_info(clientes)",
])
def test_structure_rejects_non_read_queries(sql):
    with pytest.raises(UnsafeQueryError):
        validate_read_only(sql)


def test_structure_accepts_keyword_inside_literal_and_safe_cte():
    sql = "WITH c AS (SELECT 'DROP' AS nome) SELECT nome FROM c"
    assert validate_read_only(sql) == sql
    assert run_query(str(DB), sql).rows == [("DROP",)]


def test_evidence_checks_measure_and_time_granularity():
    leader = "SELECT nome_campanha FROM campanhas_marketing GROUP BY nome_campanha ORDER BY COUNT(*) DESC LIMIT 1"
    issues = evidence_issues(
        "Qual campanha teve maior adesão?", leader, ["nome_campanha"], [("Volta às Aulas",)], False,
    )
    assert any("medida numérica" in issue for issue in issues)

    discovery = "SELECT canal FROM suporte LIMIT 3"
    issues = evidence_issues(
        "Quantas reclamações por canal?", discovery, ["canal"], [("Chat",)], False,
    )
    assert any("medida agregada" in issue for issue in issues)
    grouped_wrong = "SELECT COUNT(*) AS reclamacoes FROM suporte"
    issues = evidence_issues(
        "Quantas reclamações por canal?", grouped_wrong, ["reclamacoes"], [(51,)], False,
    )
    assert any("por canal" in issue for issue in issues)

    total = "SELECT COUNT(*) AS reclamacoes FROM suporte"
    issues = evidence_issues(
        "Qual a tendência de reclamações por canal?", total, ["reclamacoes"], [(50,)], False,
    )
    assert any("dois períodos" in issue for issue in issues)


def test_threshold_count_requires_one_total_without_ranking():
    question = "Quantos clientes fizeram pelo menos três compras pelo App?"
    wrong = "SELECT COUNT(*) FROM compras GROUP BY cliente_id HAVING COUNT(*) >= 3"
    issues = evidence_issues(question, wrong, ["total"], [(1,), (1,)], False)
    assert any("total único" in issue for issue in issues)
    assert not any("ordenar" in issue for issue in issues)

    correct = "SELECT COUNT(*) FROM (SELECT cliente_id FROM compras GROUP BY cliente_id HAVING COUNT(*) >= 3)"
    assert evidence_issues(question, correct, ["total"], [(61,)], False) == []


def test_final_text_numbers_and_leader_are_grounded():
    sql = "SELECT nome_campanha, 32 AS clientes FROM campanhas_marketing LIMIT 1"
    rows = [("Black Friday", 32)]
    assert unsupported_numbers("Black Friday: 32 clientes.", "Qual campanha lidera?", sql, rows) == []
    assert unsupported_numbers("Black Friday: 45 clientes.", "Qual campanha lidera?", sql, rows) == ["45"]
    assert missing_rank_label("Qual campanha teve maior adesão?", "Volta às Aulas: 32.", rows)


def test_swapped_category_values_are_rejected():
    rows = [("Black Friday", 32), ("Volta às Aulas", 30)]
    assert mismatched_category_values("Black Friday: 32; Volta às Aulas: 30.", rows) == []
    assert mismatched_category_values("Black Friday: 30; Volta às Aulas: 32.", rows) == [
        "Black Friday", "Volta às Aulas",
    ]
    assert mismatched_category_values("Black Friday teve 32 clientes; Volta às Aulas teve 30.", rows) == []


def test_final_text_accepts_rounded_measure_and_explicit_filter():
    rows = [("Roupas", 2.2112676)]
    assert unsupported_numbers("Roupas: média de 2,21.", "Qual média?", "SELECT 2.2112676", rows) == []
    assert unsupported_numbers(
        "Considerei resolvido = 0; total de 19.", "Quantas reclamações?",
        "SELECT COUNT(*) FROM suporte WHERE resolvido = 0", [(19,)],
    ) == []
    assert unsupported_numbers("Total: 1.234,56.", "Qual o total?", "SELECT valor", [(1234.56,)]) == []
    assert unsupported_numbers(
        "De 23/07/2024 a 22/07/2025.", "Qual a tendência?",
        "SELECT mes FROM suporte WHERE data_contato >= '2024-07-23' "
        "AND data_contato < '2025-07-23'", [],
    ) == []
    assert unsupported_numbers(
        "Há 2 meses em 2 linhas.", "Qual a tendência?", "SELECT mes FROM suporte",
        [("2024-08",), ("2024-09",)],
    ) == []
    assert unsupported_numbers(
        "Os 5 estados com mais clientes são estes.", "Liste os 5 estados.",
        "SELECT estado,COUNT(*) FROM clientes GROUP BY estado LIMIT 5",
        [("São Paulo", 6), ("Minas Gerais", 3), ("Santa Catarina", 3),
         ("Alagoas", 2), ("Espírito Santo", 2)],
    ) == []
    assert unsupported_numbers(
        "Janela de 12 meses.", "Qual a tendência no último ano?",
        "SELECT date(MAX(data_contato), '-12 months') FROM suporte", [],
    ) == []
    assert unsupported_numbers(
        "Nos últimos 12 meses.", "Qual a tendência no último ano?",
        "SELECT mes FROM suporte", [("2024-08",), ("2024-09",)],
    ) == []
    assert unsupported_numbers(
        "12 meses completos.", "Qual a tendência no último ano?",
        "SELECT mes FROM suporte", [("2024-08",), ("2024-09",)],
    ) == ["12"]


def test_agent_replaces_unsupported_final_number():
    sql = "SELECT COUNT(*) AS clientes FROM clientes"
    llm = ScriptedLLM([
        sql,
        '{"verdict": "ok", "feedback": ""}',
        '{"type": "table", "x": null, "y": null, "title": "Clientes"}',
        "Existem 999 clientes.",
    ])
    result = build_agent(settings(), llm=llm).invoke({"question": "Quantos clientes existem?", "trace": []})
    assert result["result_rows"] == [(100,)]
    assert "999" not in result["answer"]
    assert result["answer_status"] == "unconfirmed"
    assert "999" in result["caveat"]


def test_agent_does_not_conclude_from_a_name_only_ranking():
    sql = (
        "SELECT nome_campanha FROM campanhas_marketing GROUP BY nome_campanha "
        "ORDER BY COUNT(*) DESC LIMIT 1"
    )
    result = build_agent(settings(), llm=ScriptedLLM([sql, sql])).invoke({
        "question": "Qual campanha teve maior adesão dos clientes?", "trace": [],
    })
    assert result["answer_status"] == "unconfirmed"
    assert "não foi possível confirmar" in result["answer"].casefold()
    assert result["evidence_issues"]
    assert [step["step"] for step in result["trace"]].count("executar_sql") == 2


def test_agent_rejects_swapped_counts_in_final_answer():
    sql = (
        "SELECT nome_campanha, COUNT(DISTINCT cliente_id) AS clientes "
        "FROM campanhas_marketing WHERE interagiu = 1 GROUP BY nome_campanha "
        "ORDER BY clientes DESC LIMIT 2"
    )
    llm = ScriptedLLM([
        sql,
        '{"verdict": "ok", "feedback": ""}',
        '{"type": "table", "x": null, "y": null, "title": "Campanhas"}',
        "Black Friday: 30 clientes; Volta às Aulas: 32 clientes.",
    ])
    result = build_agent(settings(), llm=llm).invoke({
        "question": "Quais campanhas tiveram maior adesão?", "trace": [],
    })
    assert result["result_rows"] == [("Black Friday", 32), ("Volta às Aulas", 30)]
    assert result["answer_status"] == "unconfirmed"
    assert "Valores associados à categoria errada" in result["caveat"]
    assert "Black Friday: 30" not in result["answer"]
