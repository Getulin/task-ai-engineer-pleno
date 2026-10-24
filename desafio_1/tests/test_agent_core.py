import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.db import UnsafeQueryError, run_query, validate_read_only
from agent.graph import _route_after_execute
from agent.config import Settings, get_settings
from agent.llm import RetryingLLM
from agent.schema import discover_schema

DB = str(ROOT.parent / "data" / "anexo_desafio_1.db")

@pytest.mark.parametrize("sql", [
    "DROP TABLE clientes",
    "SELECT 1; DELETE FROM clientes",
    "UPDATE clientes SET idade = 0",
    "INSERT INTO clientes VALUES (1)",
    "",
])
def test_guard_bloqueia_escrita(sql):
    with pytest.raises(UnsafeQueryError):
        validate_read_only(sql)

@pytest.mark.parametrize("sql", [
    "SELECT * FROM clientes LIMIT 1",
    "```sql\nSELECT estado FROM clientes\n```",
    "WITH x AS (SELECT 1) SELECT * FROM x",
])
def test_guard_aceita_leitura(sql):
    assert validate_read_only(sql).lower().startswith(("select", "with"))

def test_schema_tem_tabelas_e_valores():
    schema = discover_schema(DB)
    assert "clientes" in schema and "compras" in schema
    assert "App" in schema and "Reclama" in schema

def test_schema_nao_envia_exemplos_de_nome_e_email():
    with sqlite3.connect(DB) as conn:
        nome, email = conn.execute("SELECT nome, email FROM clientes ORDER BY id LIMIT 1").fetchone()
    schema = discover_schema(DB)
    assert "nome (TEXT)" in schema and "email (TEXT)" in schema
    assert nome not in schema
    assert email not in schema

def test_run_query_read_only():
    res = run_query(DB, "SELECT estado, COUNT(*) FROM clientes GROUP BY estado")
    assert res.columns[0] == "estado"
    assert res.row_count > 0

def _settings(max_attempts=3):
    return Settings(provider="ollama", model="x", temperature=0,
                    ollama_base_url="", db_path=DB, max_repair_attempts=max_attempts,
                    row_limit=1000)

def test_router_sucesso_vai_para_viz():
    router = _route_after_execute(_settings())
    assert router({"error": None}) == "ok"

def test_router_erro_tenta_corrigir():
    router = _route_after_execute(_settings(max_attempts=3))
    assert router({"error": "boom", "repair_count": 1}) == "repair"

def test_router_esgotou_tentativas_desiste():
    router = _route_after_execute(_settings(max_attempts=3))
    assert router({"error": "boom", "repair_count": 3}) == "give_up"

def test_settings_exigem_provedor_e_modelo(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("LLM_MODEL", "modelo")
    with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
        get_settings()
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "")
    with pytest.raises(RuntimeError, match="LLM_MODEL"):
        get_settings()

def test_consulta_lenta_e_interrompida_pelo_timeout():
    infinita = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT MAX(n) FROM r"
    with pytest.raises(sqlite3.OperationalError, match="excedeu"):
        run_query(DB, infinita, timeout_s=0.2)

class _FlakyLLM:
    def __init__(self, failures, error):
        self.failures = failures
        self.error = error
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return "ok"

def test_retry_repete_erro_de_limite_de_taxa():
    waits = []
    flaky = _FlakyLLM(2, RuntimeError("429 RESOURCE_EXHAUSTED"))
    assert RetryingLLM(flaky, sleep=waits.append).invoke([]) == "ok"
    assert flaky.calls == 3
    assert waits == [2.0, 4.0]

def test_retry_nao_repete_outros_erros():
    flaky = _FlakyLLM(1, ValueError("modelo inexistente"))
    with pytest.raises(ValueError):
        RetryingLLM(flaky, sleep=lambda _: None).invoke([])
    assert flaky.calls == 1

def test_retry_desiste_apos_esgotar_tentativas():
    flaky = _FlakyLLM(10, RuntimeError("429 Too Many Requests"))
    with pytest.raises(RuntimeError):
        RetryingLLM(flaky, attempts=3, sleep=lambda _: None).invoke([])
    assert flaky.calls == 3

