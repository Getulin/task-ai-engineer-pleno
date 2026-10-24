from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.config import get_settings
from agent.graph import build_agent

EXAMPLES = [
    "Liste os 5 estados com maior número de clientes que compraram via app em maio.",
    "Quantos clientes interagiram com campanhas de WhatsApp em 2024?",
    "Quais categorias de produto tiveram o maior número de compras em média por cliente?",
    "Qual o número de reclamações não resolvidas por canal?",
    "Qual a tendência de reclamações por canal no último ano?",
]

TRACE_LABELS = {
    "descoberta_schema": "Descoberta do esquema",
    "esclarecer_pergunta": "Esclarecimento da pergunta",
    "gerar_sql": "Geração do SQL",
    "executar_sql": "Execução do SQL",
    "erro_execucao": "Erro de execução",
    "reflexao_vazio": "Revisão do resultado vazio",
    "verificar_resultado": "Verificação do resultado",
    "decidir_visualizacao": "Escolha da visualização",
    "resposta": "Resposta",
}

st.set_page_config(page_title="Assistente Virtual de Dados", page_icon="📊", layout="wide")

@st.cache_resource(show_spinner=False)
def _get_agent():
    settings = get_settings()
    return build_agent(settings), settings

def _render_viz(viz: dict, df: pd.DataFrame, key: str) -> None:
    vtype = viz.get("type", "table")
    if vtype == "bar" and viz.get("x") and viz.get("y"):
        st.plotly_chart(px.bar(df, x=viz["x"], y=viz["y"],
                               color=viz.get("series"), title=viz.get("title")),
                        use_container_width=True, key=key)
    elif vtype == "line" and viz.get("x") and viz.get("y"):
        dfx = df.sort_values(viz["x"])
        st.plotly_chart(px.line(dfx, x=viz["x"], y=viz["y"],
                                color=viz.get("series"), title=viz.get("title"),
                                markers=True), use_container_width=True, key=key)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True, key=key)

def _render_reasoning(state: dict) -> None:
    with st.expander("Etapas e consultas", expanded=False):
        for i, step in enumerate(state.get("trace", []), 1):
            label = TRACE_LABELS.get(step["step"], step["step"])
            st.markdown(f"**{i}. {label}** — {step['detail']}")
            data = step.get("data")
            if isinstance(data, str) and data.strip().lower().startswith(("select", "with")):
                st.code(data, language="sql")
            elif isinstance(data, dict) and "sql" in data:
                st.code(data["sql"], language="sql")
                if data.get("error"):
                    st.error(data["error"])
        if state.get("sql"):
            st.markdown("**SQL final executado:**")
            st.code(state["sql"], language="sql")

def _render_answer(state: dict, row_limit: int, key: str) -> None:
    st.markdown(state.get("answer", "_Sem resposta._"))
    for assumption in state.get("assumptions") or []:
        st.info(f"Premissa adotada: {assumption}")
    for note in state.get("data_notes") or []:
        st.info(note)
    if state.get("answer_status") == "unconfirmed":
        st.warning(f"Resultado não confirmado pela verificação: {state.get('caveat')}")
    elif state.get("answer_status") == "unverified":
        st.warning("A verificação automática não pôde ser executada para esta resposta.")
    if state.get("result_truncated"):
        st.warning(
            f"A consulta retornou mais de {row_limit} linhas. "
            "A visualização mostra apenas as primeiras."
        )

    cols = state.get("result_columns") or []
    rows = state.get("result_rows") or []
    if cols and rows:
        df = pd.DataFrame(rows, columns=cols)
        _render_viz(state.get("viz", {"type": "table"}), df, key)

    _render_reasoning(state)

def main() -> None:
    try:
        agent, settings = _get_agent()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    with st.sidebar:
        st.header("Configuração")
        st.markdown(f"**Provedor:** `{settings.provider}`")
        st.markdown(f"**Modelo:** `{settings.model}`")
        st.markdown(f"**Máx. correções de SQL:** {settings.max_repair_attempts}")
        st.divider()
        st.subheader("Exemplos")
        for ex in EXAMPLES:
            if st.button(ex, use_container_width=True):
                st.session_state["pending_question"] = ex

    st.title("Assistente Virtual de Dados")
    st.caption("Pergunte sobre dados, e eu investigo o banco e respondo com fatos.")

    history = st.session_state.setdefault("history", [])
    for index, exchange in enumerate(history):
        st.chat_message("user").write(exchange["question"])
        with st.chat_message("assistant"):
            if "error" in exchange:
                st.error(exchange["error"])
            else:
                _render_answer(exchange["state"], settings.row_limit, f"result-{index}")

    question = st.chat_input("Ex.: Quantas reclamações não resolvidas por canal?")
    if "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")

    if not question:
        if not history:
            st.info("Digite uma pergunta ou escolha um exemplo na barra lateral.")
        return

    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        with st.spinner("Investigando o banco de dados..."):
            try:
                state = agent.invoke({"question": question, "trace": []})
            except Exception as exc:
                error = f"Não foi possível concluir a análise: {str(exc)[:300]}"
                st.error(error)
                history.append({"question": question, "error": error})
                return

        _render_answer(state, settings.row_limit, f"result-{len(history)}")
    history.append({"question": question, "state": state})

if __name__ == "__main__":
    main()

