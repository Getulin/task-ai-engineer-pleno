from pathlib import Path

from desafio_1.agent.config import Settings
from desafio_1.agent.graph import build_agent
from desafio_1.agent.query_plan import make_plan, plan_issues
from desafio_1.eval_cases import CASES
from desafio_1.evaluate import reference_rows

DB = Path(__file__).resolve().parents[2] / "data" / "anexo_desafio_1.db"
PARTIAL = ["2024-07", "2025-07"]


def test_reference_queries_satisfy_their_plans():
    for case in CASES:
        rows = reference_rows(str(DB), case)
        assert plan_issues(make_plan(case.question), case.reference_sql, rows, PARTIAL) == [], case.id


def test_client_count_needs_purchase_event_and_unique_people():
    question = "Quantos clientes compraram pelo App em maio?"
    wrong = "SELECT COUNT(*) FROM clientes WHERE strftime('%m',data_ultima_compra)='05'"
    issues = plan_issues(make_plan(question), wrong, [(50,)], PARTIAL)
    assert any("tabela compras" in issue for issue in issues)
    assert any("data_compra" in issue for issue in issues)

    wrong = "SELECT COUNT(*) FROM compras WHERE canal='App' AND strftime('%m',data_compra)='05'"
    issues = plan_issues(make_plan(question), wrong, [(50,)], PARTIAL)
    assert any("clientes distintos" in issue for issue in issues)


def test_campaign_and_complaint_filters_are_checked():
    campaign = make_plan("Quantos clientes interagiram com campanhas de WhatsApp em 2024?")
    sql = "SELECT COUNT(DISTINCT cliente_id) FROM campanhas_marketing WHERE data_envio>='2024-01-01'"
    issues = plan_issues(campaign, sql, [(17,)], PARTIAL)
    assert any("WhatsApp" in issue for issue in issues)
    assert any("interagiu" in issue for issue in issues)

    complaint = make_plan("Qual o número de reclamações não resolvidas por canal?")
    sql = "SELECT canal,COUNT(*) FROM suporte GROUP BY canal"
    issues = plan_issues(complaint, sql, [("Chat", 20)], PARTIAL)
    assert any("tipo_contato" in issue for issue in issues)
    assert any("resolvido" in issue for issue in issues)


def test_ties_and_partial_months_require_correction():
    ranking = make_plan("Liste os 5 estados com maior número de clientes que compraram via App em maio")
    sql = """SELECT c.estado,COUNT(DISTINCT c.id) n FROM clientes c
    JOIN compras p ON p.cliente_id=c.id WHERE p.canal='App'
    AND strftime('%m',p.data_compra)='05' GROUP BY c.estado ORDER BY n DESC LIMIT 5"""
    assert any("desempate" in issue for issue in plan_issues(ranking, sql, [("SP", 6)] * 5, PARTIAL))

    trend = make_plan("Qual a tendência de reclamações por canal no último ano?")
    sql = "SELECT strftime('%Y-%m',data_contato) mes,canal,COUNT(*) FROM suporte GROUP BY mes,canal"
    issues = plan_issues(trend, sql, [("2024-07", "Chat", 2)], PARTIAL)
    assert any("meses parciais" in issue for issue in issues)


def test_attribution_question_does_not_force_interaction_filter():
    plan = make_plan("Que campanha foi enviada antes da compra, e houve interação?")
    assert ("campanhas_marketing.interagiu", "1") not in plan.filters


def test_explicit_monthly_range_requires_its_last_period():
    question = (
        "Qual percentual de cada coorte mensal de primeira compra voltou a comprar "
        "no mês seguinte, de agosto a dezembro de 2024?"
    )
    plan = make_plan(question)
    assert plan.expected_months == (
        "2024-08", "2024-09", "2024-10", "2024-11", "2024-12",
    )
    incomplete = """SELECT strftime('%Y-%m',data_compra) mes,COUNT(*) FROM compras
    WHERE data_compra>='2024-08-01' AND data_compra<'2024-12-01' GROUP BY mes"""
    rows = [(month, 1) for month in plan.expected_months[:-1]]
    assert any("2024-12" in issue for issue in plan_issues(plan, incomplete, rows, PARTIAL))


def test_agent_revises_cohort_query_that_omits_december():
    case = next(case for case in CASES if case.id == "retencao_coorte_mes_seguinte")
    wrong = case.reference_sql.replace("<'2025-01-01'", "<'2024-12-01'")

    class ScriptedLLM:
        def __init__(self):
            self.replies = iter([
                wrong, case.reference_sql, '{"verdict":"ok"}',
                '{"type":"table","x":null,"y":null,"title":"Coortes"}',
                "Retenção por coorte.",
            ])

        def invoke(self, messages):
            return next(self.replies)

    settings = Settings(
        provider="ollama", model="test", temperature=0, ollama_base_url="",
        db_path=str(DB), max_repair_attempts=3, row_limit=1000,
    )
    result = build_agent(settings, llm=ScriptedLLM()).invoke({
        "question": case.question, "trace": [],
    })
    assert result["answer_status"] == "confirmed"
    assert result["review_count"] == 1
    assert len(result["result_rows"]) == 5
    assert "2024-12" in result["review_history"][0]["feedback"]
