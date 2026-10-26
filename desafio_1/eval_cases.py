from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    reference_sql: str
    comparison: Literal["exact", "unordered", "contains"] = "unordered"


CASES = [
    EvalCase(
        "estados_app_maio",
        "Liste os 5 estados com maior número de clientes que compraram via app em maio.",
        """SELECT c.estado, COUNT(DISTINCT c.id) AS clientes
        FROM clientes c JOIN compras p ON p.cliente_id=c.id
        WHERE p.canal='App' AND strftime('%m',p.data_compra)='05'
        GROUP BY c.estado ORDER BY clientes DESC,c.estado LIMIT 5""",
        "exact",
    ),
    EvalCase(
        "whatsapp_2024",
        "Quantos clientes interagiram com campanhas de WhatsApp em 2024?",
        """SELECT COUNT(DISTINCT cliente_id) FROM campanhas_marketing
        WHERE canal='WhatsApp' AND interagiu=1
        AND data_envio>='2024-01-01' AND data_envio<'2025-01-01'""",
    ),
    EvalCase(
        "media_compras_categoria",
        "Quais categorias de produto tiveram o maior número de compras em média por cliente?",
        """SELECT categoria, 1.0*COUNT(*)/COUNT(DISTINCT cliente_id) AS media
        FROM compras GROUP BY categoria ORDER BY media DESC,categoria""",
        "contains",
    ),
    EvalCase(
        "reclamacoes_canal",
        "Qual o número de reclamações não resolvidas por canal?",
        """SELECT canal,COUNT(*) FROM suporte
        WHERE tipo_contato='Reclamação' AND resolvido=0 GROUP BY canal""",
    ),
    EvalCase(
        "tendencia_reclamacoes",
        "Qual a tendência de reclamações por canal no último ano?",
        """SELECT strftime('%Y-%m',data_contato) mes,canal,COUNT(*) FROM suporte
        WHERE tipo_contato='Reclamação' AND data_contato>='2024-08-01'
        AND data_contato<'2025-07-01' GROUP BY mes,canal""",
    ),
    EvalCase(
        "campanha_lider",
        "Qual a campanha com a maior adesão de clientes, e quantos clientes foram?",
        """SELECT nome_campanha,COUNT(DISTINCT cliente_id) clientes
        FROM campanhas_marketing WHERE interagiu=1 GROUP BY nome_campanha
        ORDER BY clientes DESC,nome_campanha LIMIT 1""",
    ),
    EvalCase(
        "campanhas_adesao",
        "Quantos clientes distintos interagiram com cada campanha?",
        """SELECT nome_campanha,COUNT(DISTINCT cliente_id) FROM campanhas_marketing
        WHERE interagiu=1 GROUP BY nome_campanha""",
    ),
    EvalCase(
        "app_setembro",
        "Quantos clientes efetuaram compras pelo App em setembro, em todos os anos disponíveis?",
        """SELECT COUNT(DISTINCT cliente_id) FROM compras
        WHERE canal='App' AND strftime('%m',data_compra)='09'""",
    ),
    EvalCase(
        "clientes_sem_app",
        "Quantos clientes nunca compraram pelo App?",
        """SELECT COUNT(*) FROM clientes c WHERE NOT EXISTS
        (SELECT 1 FROM compras p WHERE p.cliente_id=c.id AND p.canal='App')""",
    ),
    EvalCase(
        "compradores_app_mes",
        "Quantos clientes distintos compraram pelo App em cada mês completo de 2024?",
        """SELECT strftime('%Y-%m',data_compra) mes,COUNT(DISTINCT cliente_id)
        FROM compras WHERE canal='App' AND data_compra>='2024-08-01'
        AND data_compra<'2025-01-01' GROUP BY mes""",
    ),
    EvalCase(
        "reclamantes_por_canal",
        "Quantos clientes distintos fizeram reclamações não resolvidas por canal?",
        """SELECT canal,COUNT(DISTINCT cliente_id) FROM suporte
        WHERE tipo_contato='Reclamação' AND resolvido=0 GROUP BY canal""",
    ),
    EvalCase(
        "compras_app_categoria",
        "Quantas compras pelo App ocorreram em cada categoria de produto?",
        """SELECT categoria,COUNT(*) FROM compras WHERE canal='App'
        GROUP BY categoria""",
    ),
    EvalCase(
        "compradores_campanhas_whatsapp",
        "Dos clientes que compraram pelo App em 2024, quantos interagiram com campanhas de WhatsApp em 2024?",
        """SELECT COUNT(DISTINCT p.cliente_id) FROM compras p
        WHERE p.canal='App' AND p.data_compra>='2024-01-01' AND p.data_compra<'2025-01-01'
        AND EXISTS (SELECT 1 FROM campanhas_marketing m WHERE m.cliente_id=p.cliente_id
        AND m.canal='WhatsApp' AND m.interagiu=1 AND m.data_envio>='2024-01-01'
        AND m.data_envio<'2025-01-01')""",
    ),
    EvalCase(
        "ticket_medio_app_categoria",
        "Qual o valor médio das compras pelo App em cada categoria?",
        """SELECT categoria,AVG(valor) FROM compras WHERE canal='App'
        GROUP BY categoria""",
    ),
    EvalCase(
        "taxa_reclamacoes_nao_resolvidas",
        "Qual percentual das reclamações ficou sem resolução em cada canal?",
        """SELECT canal,100.0*SUM(CASE WHEN resolvido=0 THEN 1 ELSE 0 END)/COUNT(*)
        FROM suporte WHERE tipo_contato='Reclamação' GROUP BY canal""",
    ),
    EvalCase(
        "compradores_app_2025_mensal",
        "Quantos clientes distintos compraram pelo App em cada mês completo de janeiro a junho de 2025?",
        """SELECT strftime('%Y-%m',data_compra),COUNT(DISTINCT cliente_id)
        FROM compras WHERE canal='App' AND data_compra>='2025-01-01'
        AND data_compra<'2025-07-01' GROUP BY strftime('%Y-%m',data_compra)""",
    ),
    EvalCase(
        "interacoes_campanhas_estado_2024",
        "Quantos clientes de cada estado interagiram com campanhas em 2024?",
        """SELECT c.estado,COUNT(DISTINCT m.cliente_id)
        FROM campanhas_marketing m JOIN clientes c ON c.id=m.cliente_id
        WHERE m.interagiu=1 AND m.data_envio>='2024-01-01'
        AND m.data_envio<'2025-01-01' GROUP BY c.estado""",
    ),
    EvalCase(
        "clientes_sem_suporte",
        "Quantos clientes nunca fizeram contato com o suporte?",
        """SELECT COUNT(*) FROM clientes c WHERE NOT EXISTS
        (SELECT 1 FROM suporte s WHERE s.cliente_id=c.id)""",
    ),
    EvalCase(
        "compradores_app_com_suporte_posterior",
        "Quantos clientes que compraram pelo App em 2024 contataram o suporte depois de uma dessas compras?",
        """SELECT COUNT(DISTINCT p.cliente_id) FROM compras p
        WHERE p.canal='App' AND p.data_compra>='2024-01-01' AND p.data_compra<'2025-01-01'
        AND EXISTS (SELECT 1 FROM suporte s WHERE s.cliente_id=p.cliente_id
        AND s.data_contato>p.data_compra)""",
    ),
    EvalCase(
        "clientes_tres_compras_app",
        "Quantos clientes fizeram pelo menos três compras pelo App?",
        """SELECT COUNT(*) FROM (SELECT cliente_id FROM compras WHERE canal='App'
        GROUP BY cliente_id HAVING COUNT(*)>=3)""",
    ),
    EvalCase(
        "retencao_coorte_mes_seguinte",
        "Qual percentual de cada coorte mensal de primeira compra voltou a comprar no mês seguinte, de agosto a dezembro de 2024?",
        """WITH primeira AS (
          SELECT cliente_id,MIN(data_compra) data_primeira FROM compras GROUP BY cliente_id
        ), coorte AS (
          SELECT cliente_id,strftime('%Y-%m',data_primeira) mes FROM primeira
          WHERE data_primeira>='2024-08-01' AND data_primeira<'2025-01-01'
        )
        SELECT c.mes,100.0*COUNT(DISTINCT CASE WHEN EXISTS (
          SELECT 1 FROM compras p WHERE p.cliente_id=c.cliente_id
          AND strftime('%Y-%m',p.data_compra)=strftime('%Y-%m',date(c.mes||'-01','+1 month'))
        ) THEN c.cliente_id END)/COUNT(DISTINCT c.cliente_id)
        FROM coorte c GROUP BY c.mes ORDER BY c.mes""",
    ),
]
