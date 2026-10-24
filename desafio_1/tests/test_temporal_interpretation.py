import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.config import Settings
from agent.graph import build_agent
from agent.temporal import interpret_question

DB = ROOT.parent / "data" / "anexo_desafio_1.db"


@pytest.mark.parametrize("name, number", [
    ("janeiro", "01"), ("fevereiro", "02"), ("março", "03"),
    ("abril", "04"), ("maio", "05"), ("junho", "06"),
    ("julho", "07"), ("agosto", "08"), ("setembro", "09"),
    ("outubro", "10"), ("novembro", "11"), ("dezembro", "12"),
])
def test_each_unqualified_month_covers_all_available_years(name, number):
    scope = interpret_question(f"Quantos clientes compraram em {name}?")
    assert f"{number}; nenhum ano" in scope.guidance
    assert "TODAS as ocorrencias" in scope.guidance
    assert scope.assumption is not None
    assert scope.clarification is None


def test_explicit_year_and_latest_month_override_all_years():
    explicit = interpret_question("Quantos compraram em setembro de 2024?")
    assert "2024" in explicit.guidance
    assert explicit.assumption is None

    latest = interpret_question("Quantos compraram no julho mais recente?")
    assert "mais recente" in latest.guidance
    assert latest.assumption is not None


def test_plural_month_and_multiple_months():
    scope = interpret_question("Compare compras em todos os julhos e agostos")
    assert "07, 08" in scope.guidance
    assert scope.clarification is None
    assert "meses citados" in scope.assumption


def test_relative_period_does_not_mean_latest_named_month():
    scope = interpret_question("Compare compras em julho nos últimos dois anos")
    assert "periodo relativo" in scope.guidance
    assert "unica ocorrencia" in scope.guidance
    assert scope.assumption is None


class NoCallsLLM:
    def invoke(self, messages):
        raise AssertionError("O modelo nao deve receber uma pergunta sem evento definido")


def test_ambiguous_customer_month_asks_for_event_without_generating_sql():
    settings = Settings(
        provider="ollama", model="test", temperature=0, ollama_base_url="",
        db_path=str(DB), max_repair_attempts=3, row_limit=1000,
    )
    agent = build_agent(settings, llm=NoCallsLLM())
    result = agent.invoke({"question": "Liste os estados com menos clientes em julho", "trace": []})
    assert "Qual evento" in result["answer"]
    assert not result.get("sql")
    assert result["trace"][-1]["step"] == "esclarecer_pergunta"
