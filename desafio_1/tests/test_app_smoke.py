from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_app_starts_with_local_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "local-test")
    app = Path(__file__).resolve().parents[1] / "app.py"

    result = AppTest.from_file(str(app)).run(timeout=20)

    assert not result.exception
    assert result.title[0].value == "Assistente Virtual de Dados"
