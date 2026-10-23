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
    "Liste os 5 estados com maior numero de clientes que compraram via app em maio.",
    "Quantos clientes interagiram com campanhas de WhatsApp em 2024?",
    "Quais categorias de produto tiveram o maior numero de compras em media por cliente?",
    "Qual o numero de reclamacoes nao resolvidas por canal?",
    "Qual a tendencia de reclamacoes por canal no ultimo ano?",
]

st.set_page_config(page_title="Assistente Virtual de Dados", page_icon="📊", layout="wide")

@st.cache_resource(show_spinner=False)
def _get_agent():
    settings = get_settings()
    return build_agent(settings), settings

def _render_viz(viz: dict, df: pd.DataFrame) -> None:
    vtype = viz.get("type", "table")
    if vtype == "bar" and viz.get("x") and viz.get("y"):
        st.plotly_chart(px.bar(df, x=viz["x"], y=viz["y"],
                               color=viz.get("series"), title=viz.get("title")),
                        use_container_width=True)
    elif vtype == "line" and viz.get("x") and viz.get("y"):
        dfx = df.sort_values(viz["x"])
        st.plotly_chart(px.line(dfx, x=viz["x"], y=viz["y"],
                                color=viz.get("series"), title=viz.get("title"),
                                markers=True), use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

def _render_reasoning(state: dict) -> None:
    with st.expander("Etapas e consultas", expanded=False):
        for i, step in enumerate(state.get("trace", []), 1):
            st.markdown(f"**{i}. {step['step']}** — {step['detail']}")
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

def main() -> None:
    agent, settings = _get_agent()

    with st.sidebar:
        st.header("Configuracao")
        st.markdown(f"**Provedor:** `{settings.provider}`")
        st.markdown(f"**Modelo:** `{settings.model}`")
        st.markdown(f"**Max. correcoes de SQL:** {settings.max_repair_attempts}")
        st.divider()
        st.subheader("Exemplos")
        for ex in EXAMPLES:
            if st.button(ex, use_container_width=True):
                st.session_state["pending_question"] = ex

    st.title("Assistente Virtual de Dados")
    st.caption("Pergunte em linguagem natural — eu investigo o banco e respondo com dados.")

    question = st.chat_input("Ex.: Quantas reclamacoes nao resolvidas por canal?")
    if "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")

    if not question:
        st.info("Digite uma pergunta ou escolha um exemplo na barra lateral.")
        return

    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        with st.spinner("Investigando o banco de dados..."):
            state = agent.invoke({"question": question, "trace": []})

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
                f"A consulta retornou mais de {settings.row_limit} linhas. "
                "A visualização mostra apenas as primeiras."
            )

        cols = state.get("result_columns") or []
        rows = state.get("result_rows") or []
        if cols and rows:
            df = pd.DataFrame(rows, columns=cols)
            _render_viz(state.get("viz", {"type": "table"}), df)

        _render_reasoning(state)

if __name__ == "__main__":
    main()

