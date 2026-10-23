from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .config import Settings, get_settings
from .llm import build_llm
from .nodes import make_nodes
from .state import AgentState

_MAX_EMPTY_RETRIES = 1

def _route_after_execute(settings: Settings):
    def router(state: AgentState) -> str:
        if state.get("error"):
            if state.get("repair_count", 0) < settings.max_repair_attempts:
                return "repair"
            return "give_up"
        if state.get("last_was_empty") and state.get("empty_retries", 0) < _MAX_EMPTY_RETRIES:
            return "reconsider"
        return "ok"
    return router


def _route_after_assess(state: AgentState) -> str:
    if state.get("review_needed"):
        return "review"
    return "ok"


def build_agent(settings: Settings | None = None, llm=None):
    """Compila e devolve o agente (um objeto LangGraph executavel)."""
    settings = settings or get_settings()
    llm = llm or build_llm(settings)
    nodes = make_nodes(llm, settings)

    g = StateGraph(AgentState)
    g.add_node("discover", nodes["discover"])
    g.add_node("generate_sql", nodes["generate_sql"])
    g.add_node("execute_sql", nodes["execute_sql"])
    g.add_node("reconsider", nodes["reconsider"])
    g.add_node("assess_result", nodes["assess_result"])
    g.add_node("decide_viz", nodes["decide_viz"])
    g.add_node("synthesize", nodes["synthesize"])

    g.add_edge(START, "discover")
    g.add_edge("discover", "generate_sql")
    g.add_edge("generate_sql", "execute_sql")
    g.add_conditional_edges(
        "execute_sql",
        _route_after_execute(settings),
        {
            "repair": "generate_sql",
            "reconsider": "reconsider",
            "give_up": "synthesize",
            "ok": "assess_result",
        },
    )
    g.add_edge("reconsider", "generate_sql")
    g.add_conditional_edges(
        "assess_result",
        _route_after_assess,
        {"review": "generate_sql", "ok": "decide_viz"},
    )
    g.add_edge("decide_viz", "synthesize")
    g.add_edge("synthesize", END)

    return g.compile()

def answer_question(question: str, settings: Settings | None = None) -> AgentState:
    """Atalho sincrono: roda o agente para uma pergunta e devolve o estado final."""
    agent = build_agent(settings)
    return agent.invoke({"question": question, "trace": []})

