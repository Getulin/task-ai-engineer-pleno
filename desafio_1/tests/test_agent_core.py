import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.db import UnsafeQueryError, run_query, validate_read_only
from agent.graph import _route_after_execute
from agent.config import Settings
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

