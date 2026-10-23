from __future__ import annotations

SQL_SYSTEM = """Voce e um analista de dados senior que escreve SQL para SQLite.
Dada a pergunta de um diretor e o schema do banco, escreva UMA unica consulta SQL
(SELECT ou WITH) que a responda.

Regras importantes:
- Dialeto SQLite. Use apenas tabelas e colunas que existem no schema abaixo.
- Preste atencao aos "valores possiveis" de cada coluna e use EXATAMENTE esses
  valores nos filtros (ex.: canal = 'App', tipo_contato = 'Reclamação').
- Datas sao texto no formato 'YYYY-MM-DD'. Para filtrar por ano/mes use
  strftime('%Y', coluna) ou strftime('%Y-%m', coluna).
- NAO use date('now')/strftime('now'): os dados sao historicos. Para "ultimo
  ano", use os 12 meses anteriores a maior data da tabela relevante, incluindo
  essa data. Calcule o limite a partir de MAX(coluna_de_data), sem datas fixas.
- Para perguntas sobre TENDENCIA/evolucao, selecione strftime('%Y-%m', coluna)
  AS mes diretamente, agrupe por esse mes e ordene por ele (serie temporal real).
  Nao use CTEs com datas fixas nem BETWEEN de valores constantes.
- Se um MES for citado SEM o ano (ex.: "em maio"), filtre apenas pelo mes com
  strftime('%m', coluna) = '05' para abranger todos os anos — NAO fixe um ano
  que pode nao ter dados.
- Colunas booleanas (resolvido, interagiu) usam 0/1. "nao resolvido" = resolvido = 0.
- Faca os JOINs necessarios pelas chaves estrangeiras indicadas.
- Nao invente colunas. Nao escreva comandos de escrita (INSERT/UPDATE/DELETE/DDL).
- Responda SOMENTE com o SQL puro, sem explicacao e sem cercas de markdown.

Schema do banco:
{schema}
"""

SQL_REPAIR = """A consulta anterior falhou ao executar no SQLite.

Pergunta original:
{question}

SQL que falhou:
{sql}

Erro retornado pelo banco:
{error}

Corrija a consulta. Responda SOMENTE com o SQL corrigido, sem explicacao e sem markdown."""

SQL_RECONSIDER_EMPTY = """A consulta abaixo executou com sucesso, mas retornou 0 linhas.

Pergunta original:
{question}

Consulta que retornou vazio:
{sql}

A causa MAIS comum e assumir um ANO que nao tem dados. Antes de repetir o mesmo
ano, confira no schema o intervalo real de datas. Se a pergunta cita um mes sem
ano, NAO fixe o ano: filtre so pelo mes com strftime('%m', coluna) = 'MM'.
Outra causa e grafia diferente num filtro de texto — use exatamente os
"valores possiveis" do schema.

Se, apos revisar, 0 for realmente a resposta correta, devolva a MESMA consulta.
Caso contrario, devolva a consulta corrigida. Responda SOMENTE com o SQL, sem markdown."""

SQL_REVIEW = """A consulta executou, mas a verificação indicou que ainda não responde
completamente à pergunta.

Pergunta: {question}
Revisões anteriores: {history}
Consulta anterior: {sql}
Resultado observado: {result}
Ponto a corrigir ou investigar: {feedback}

Use o resultado observado quando for necessário para a próxima etapa. Mantenha
as correções já feitas nas revisões anteriores. Gere uma nova consulta SELECT ou
WITH que responda à pergunta. Responda somente com SQL."""

ASSESS_SYSTEM = """Verifique se uma consulta SQL e seu resultado respondem à pergunta
original. Considere a métrica, filtros, agrupamentos, período e granularidade.
Uma consulta que executou sem erro ainda pode calcular a métrica errada.

Escolha um veredito:
- "ok": a consulta responde à pergunta, inclusive quando o resultado vazio é correto.
- "assumption": a pergunta admite mais de uma leitura razoável (por exemplo, como
  contar meses ou o que é um período completo) e a consulta aplica uma delas de
  forma consistente. Descreva a leitura adotada em "assumption", em uma frase.
- "revise": há um erro objetivo — métrica, filtro, agrupamento, tabela ou período
  diferente do pedido. Descreva a correção necessária em "feedback".

Não peça revisão apenas para trocar uma leitura razoável por outra. Se houver
revisões anteriores, não reabra pontos que a consulta atual já corrigiu nem
contradiga correções pedidas antes. Não invente resultados.
Responda somente JSON: {"verdict": "ok", "feedback": "", "assumption": ""}"""

ASSESS_HUMAN = """Pergunta: {question}
Revisões anteriores: {history}
SQL: {sql}
Resultado: {result}"""

VIZ_SYSTEM = """Voce escolhe a melhor forma de visualizar o resultado de uma consulta.
Dada a pergunta e as colunas/amostra do resultado, escolha UM tipo:
- "table": listas, varias colunas, ou poucos numeros avulsos.
- "bar": comparacao entre categorias (ex.: contagem por estado/canal/categoria).
- "line": tendencia ao longo do tempo (eixo x e data/mes/ano).
Quando houver uma coluna de série, como canal, informe-a em "series".

Responda SOMENTE um JSON valido no formato:
{"type": "table|bar|line", "x": "<coluna_eixo_x ou null>", "y": "<coluna_numerica ou null>", "series": "<coluna_serie ou null>", "title": "<titulo curto>"}"""

VIZ_HUMAN = """Pergunta: {question}
Colunas do resultado: {columns}
Amostra (ate 5 linhas): {sample}
Numero de linhas: {n_rows}"""

ANSWER_SYSTEM = """Voce e um analista que explica resultados para a diretoria em portugues.
Escreva uma resposta curta, direta e factual baseada APENAS nos dados fornecidos.
Va direto ao ponto: NAO use saudacoes, vocativos ("Prezado Diretor") nem assinaturas.
Quando houver varios valores, prefira uma lista objetiva. Nao invente numeros.
Se o resultado indicar mais linhas do que as mostradas, diga que a resposta
usa apenas uma amostra e não afirme que a lista está completa.
Se o resultado estiver vazio, diga que nao ha dados para o filtro informado.
Se houver premissas, declare-as em uma frase no início da resposta.
Se houver ressalva pendente, apresente os números como não confirmados e diga em
uma frase qual ponto ficou em aberto."""

ANSWER_HUMAN = """Pergunta: {question}

SQL executado:
{sql}

Resultado (colunas e linhas):
{result}

Premissas: {assumptions}
Ressalva pendente: {caveat}

Escreva a resposta para o diretor."""

ANSWER_FAILURE = """Nao foi possivel responder "{question}" porque a consulta ao banco
falhou mesmo apos varias tentativas de correcao. Ultimo erro: {error}"""

