# Assistente de dados — Desafio 1

Aplicação em Python para responder perguntas de negócio sobre o banco SQLite fornecido no desafio. O usuário faz uma pergunta em português; o agente consulta o esquema do banco, gera SQL, executa a consulta e apresenta a resposta com tabela ou gráfico, junto com as consultas executadas.

Este repositório implementa o **Desafio 1**.

## Execução

Requer Python 3.11 ou superior. O banco de exemplo está em `data/anexo_desafio_1.db`. Antes de rodar, defina o provedor de LLM no `.env` (veja [Configuração](#configuração)). Para rodar localmente sem chave de API, veja [docs/ollama.md](docs/ollama.md).

Clone o repositório e execute os comandos abaixo na raiz do projeto:

```bash
git clone https://github.com/Getulin/task-ai-engineer-pleno.git
cd task-ai-engineer-pleno
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# defina LLM_PROVIDER e LLM_MODEL no .env
.\.venv\Scripts\python -m streamlit run desafio_1/app.py
```

### Linux ou macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# defina LLM_PROVIDER e LLM_MODEL no .env
.venv/bin/python -m streamlit run desafio_1/app.py
```

### Configuração

O `.env` define o provedor, o modelo e os limites e é ignorado pelo Git. `LLM_PROVIDER` e `LLM_MODEL` são obrigatórios. Para provedores remotos, inclua também a chave correspondente. O banco já está no repositório; `DB_PATH` só precisa ser alterado se você usar outro arquivo.

Para usar o Gemini, por exemplo, preencha estas linhas no `.env` com uma chave sua:

```env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=SUA_CHAVE_AQUI
```

Depois de alterar o `.env` ou o código do agente, encerre o Streamlit com `Ctrl+C` e execute novamente o comando de inicialização. O agente é mantido em cache durante a execução.

| Variável | Uso |
| --- | --- |
| `LLM_PROVIDER` | `ollama`, `gemini`, `openai` ou `groq` |
| `LLM_MODEL` | Modelo do provedor escolhido |
| `LLM_TEMPERATURE` | Temperatura solicitada ao modelo (padrão: `0`; alguns modelos ignoram esse parâmetro) |
| `OLLAMA_BASE_URL` | Endereço do Ollama quando `LLM_PROVIDER=ollama`; veja [docs/ollama.md](docs/ollama.md) |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY` | Chave do provedor escolhido |
| `DB_PATH` | Caminho do SQLite, relativo à raiz do projeto ou absoluto (padrão: `data/anexo_desafio_1.db`) |
| `LLM_REQUESTS_PER_SECOND` | Limite local de chamadas ao modelo; `0` desativa. Ajuste conforme a cota da sua conta. |
| `LLM_MAX_CALLS_PER_QUESTION` | Limite de chamadas lógicas ao modelo em cada pergunta (padrão: `12`). |
| `LLM_INPUT_USD_PER_MILLION`, `LLM_OUTPUT_USD_PER_MILLION` | Preços do modelo configurado por milhão de tokens; `0` deixa o custo indisponível. |
| `LLM_MAX_ESTIMATED_COST_USD` | Interrompe novas chamadas quando a estimativa acumulada atinge o valor configurado. `0` desativa; exige os preços acima. |
| `SQL_MAX_REPAIR_ATTEMPTS` | Número máximo de execuções com erro antes de desistir (padrão: `3`) |
| `SQL_ROW_LIMIT`, `SQL_TIMEOUT_SECONDS` | Limites por consulta (padrão: 1.000 linhas e 10 s) |

A interface mostra chamadas, duração e tokens informados pelo provedor sem gravar prompts ou linhas do banco em um log de uso. A estimativa de custo depende dos preços configurados e dos tokens fornecidos pela API. O limite de custo é conferido antes da próxima chamada; a última chamada pode ultrapassar o teto estimado. Tentativas internas de repetição por limite de taxa contam como uma chamada lógica nessa medição.

### Testes

```powershell
.\.venv\Scripts\python -m pytest desafio_1/tests -q
```

No Linux ou macOS, use `.venv/bin/python -m pytest desafio_1/tests -q`.

### Avaliação de perguntas

`desafio_1/eval_cases.py` reúne perguntas de referência com SQL independente. A comparação usa os valores retornados pelo banco; diferenças de texto ou de aliases no SQL não contam como erro. Para conferir as consultas de referência sem chamar o modelo:

```bash
python -m desafio_1.evaluate
```

Para executar o conjunto com o provedor configurado no `.env` e guardar o relatório local:

```bash
python -m desafio_1.evaluate --live --output eval_reports/resultado.json
```

`--case ID` seleciona uma pergunta e `--repeats N` repete cada pergunta até cinco vezes. O relatório inclui os resultados, SQL gerado, estado da resposta, duração, chamadas ao modelo e tokens quando informados pelo provedor. `eval_reports/` é ignorado pelo Git. A comparação automática identifica divergências de valores; casos ambíguos ou com colunas adicionais podem precisar de revisão humana.

## Fluxo e arquitetura

```text
pergunta
  → continuação: reescrita com a última pergunta interpretada
     └─ continuação dependente sem referência ou leitura incerta: pede esclarecimento
  → descoberta de tabelas, colunas, relações e valores do SQLite
  → interpretação do período citado
     └─ "clientes em um mês" sem evento definido: pede esclarecimento
  → plano verificável: tabelas, data do evento, filtros e contagem de pessoas
  → geração, validação estrutural e execução de SQL
     ├─ erro de SQL: nova tentativa com a mensagem de erro
     └─ resultado vazio ou contagem zero: confere categorias e datas relevantes;
        depois reconsidera os filtros uma vez
  → verificação de aderência entre pergunta, SQL e resultado
     ├─ regras sobre contagem, agrupamento, ranking, tendência e resultado truncado
     ├─ leitura ambígua: segue com a premissa declarada
     └─ erro objetivo: até uma consulta adicional; se faltar evidência, não conclui
  → escolha de tabela, barras ou linhas
  → conferência dos números e do líder citados no texto final
  → resposta e registro das etapas/consultas
```

O agente é um grafo de estados em LangGraph (`desafio_1/agent/graph.py`). O grafo deixa explícitos os pontos em que o agente volta a gerar SQL e limita quantas vezes isso acontece, o que mantém o comportamento previsível e cada etapa visível na interface.

| Módulo | Responsabilidade |
| --- | --- |
| `schema.py` | Lê o esquema em tempo de execução: tabelas, colunas, relações, valores de colunas de baixa cardinalidade, intervalos de datas e meses cobertos só em parte. Exemplos de colunas pessoais reconhecidas são omitidos do contexto do modelo. |
| `context.py` | Identifica mensagens que dependem da pergunta anterior. |
| `temporal.py` | Interpreta os meses citados na pergunta e identifica quando falta definir o evento que associa clientes a um mês. |
| `query_plan.py` | Extrai exigências explícitas da pergunta e confere sua presença na consulta gerada: evento, data, filtros, clientes distintos, desempate e meses parciais. |
| `investigation.py` | Quando uma consulta volta vazia, lê categorias e limites de data dos eventos pertinentes em conexão somente leitura, sem consultar valores pessoais. |
| `db.py` | Valida a árvore sintática do SQL com SQLGlot e executa uma consulta `SELECT` por vez, com conexão somente leitura, autorização do SQLite e limites de linhas e tempo. |
| `evidence.py` | Confere requisitos objetivos da pergunta contra o SQL e o resultado; verifica números e líderes citados na resposta. |
| `nodes.py` | Gera, executa, corrige e verifica o SQL; escolhe a visualização e redige a resposta. |
| `llm.py` | Cria o modelo do provedor configurado e repete chamadas recusadas por limite de taxa. |
| `app.py` | Interface Streamlit com resposta, gráfico, avisos, histórico da sessão e a seção “Etapas e consultas”. Envia a última pergunta interpretada para resolver continuações. |

A verificação combina regras determinísticas com a avaliação do modelo. As regras exigem medidas numéricas em contagens e rankings, agrupamento pelas dimensões pedidas e série de pelo menos dois períodos para tendências; resultados cortados pelo limite de linhas não sustentam uma conclusão completa. O modelo avalia a métrica, os filtros, o período e as ambiguidades da pergunta. Um erro objetivo pode gerar uma consulta adicional, que recebe as correções anteriores. Se uma exigência determinística continuar sem evidência, a interface apresenta os dados e o SQL sem afirmar uma conclusão. Ressalvas do verificador do modelo são mostradas ao usuário.

Antes de exibir a resposta redigida pelo modelo, o agente confere seus números com as medidas retornadas e os períodos da consulta. Em resultados simples de duas colunas, confere também se cada número foi associado à categoria correta. Em um ranking com um único líder, confere se o nome retornado aparece no texto. Uma afirmação sem suporte substitui a síntese por um aviso; as regras não demonstram, por si só, que toda interpretação de negócio está correta.

As consultas de negócio do agente são geradas em tempo de execução. O código usa SQL fixo para inspecionar o esquema, e os testes contêm consultas de referência. O agente omite exemplos de colunas pessoais reconhecidas no esquema e mascara resultados quando o nome da coluna é reconhecido como pessoal. Esse filtro baseado em nomes não cobre aliases ou expressões que incluam dados pessoais. A tabela exibida localmente mantém os valores originais.

As datas do banco vão, em conjunto, de 22/07/2024 a 22/07/2025; o intervalo varia entre as tabelas. O agente recebe a orientação de excluir meses incompletos de séries mensais e coortes (julho de 2024 e julho de 2025) e de incluir todos os registros em totais e médias. Um mês citado pelo nome sem ano abrange todas as ocorrências desse mês nos anos disponíveis; “mais recente” ou um ano explícito alteram esse recorte. Em contagens após um evento, o mês do evento é M0, “mês seguinte” é M+1 e “terceiro mês” é M+3. As regras determinísticas cobrem incompatibilidades verificáveis; a interpretação da métrica de negócio ainda depende da avaliação do modelo.

O agente escolhe entre tabela, barras e linhas conforme a pergunta e as colunas retornadas. Pedidos explícitos de tabela, gráfico de barras ou gráfico de linhas prevalecem quando as colunas permitem o gráfico. A interface avisa quando a consulta excede o limite de linhas. O histórico mantém perguntas e resultados visíveis durante a sessão. Uma continuação como “e por estado?” usa a última pergunta interpretada para formar uma consulta completa; a interpretação aparece na interface. Perguntas independentes não usam esse contexto, e resultados anteriores não são reenviados ao modelo nessa etapa.

## Consultas testadas

Os valores abaixo são referências conferidas com consultas SQL ao banco. `desafio_1/tests/test_business_questions.py` cobre parte dessas métricas; outras foram verificadas manualmente. O SQL produzido pelo modelo pode variar entre execuções, então a tabela não garante que toda resposta do agente repetirá exatamente estes valores.

| Pergunta | Resultado |
| --- | --- |
| Liste os 5 estados com maior número de clientes que compraram via app em maio. | São Paulo 6; Minas Gerais 3; Santa Catarina 3; Alagoas 2; Espírito Santo 2. Paraná também tem 2 e fica fora pelo desempate alfabético usado na consulta de referência. |
| Quantos clientes interagiram com campanhas de WhatsApp em 2024? | 17 |
| Quais categorias de produto tiveram o maior número de compras em média por cliente? | Roupas 2,21; Viagens 2,16; Livros 1,98 |
| Qual o número de reclamações não resolvidas por canal? | Telefone 19; Chat 18; E-mail 14 |
| Qual a tendência de reclamações por canal no último ano? | Série mensal por canal, com 11 meses completos de agosto de 2024 a junho de 2025 |
| Qual percentual de cada coorte de primeira compra voltou a comprar no mês seguinte e no terceiro mês? | Agosto de 2024: 43 clientes, 37,21% e 60,47%; setembro: 13 clientes, 69,23% e 38,46% |
| Quantos clientes efetuaram pagamentos pelo app em setembro? | 22 clientes distintos com compras via App. O filtro abrange todos os setembros; o banco contém apenas setembro de 2024. |
| Qual a campanha com a maior adesão de clientes? | Black Friday, com 32 clientes distintos que interagiram. |
| Qual a campanha com a maior adesão de clientes, e quantos clientes foram? | Black Friday, 32 clientes distintos que interagiram. |

Na pergunta sobre pagamentos, `compras` é usada como aproximação, pois o banco não registra pagamentos separadamente. Nas duas últimas, adesão significa quantidade de clientes distintos com `interagiu = 1`. Black Friday tem 32 clientes nessa condição, contra 30 de Volta às Aulas. Se medida como proporção dos clientes alcançados, Black Friday também lidera: 32 de 45 (71,11%). Contar envios levaria a outro ranking e não mede adesão.

O banco não atribui compras a campanhas. Em perguntas sobre qual campanha "atraiu" um comprador, o agente verifica campanhas enviadas antes da compra e informa se houve interação; a ordem das datas, por si só, não demonstra que a campanha causou a compra.

## Capacidades atuais

- Consultas SQL validadas pela estrutura da instrução e executadas em conexão somente leitura, com tentativa de correção após erro e uma conferência de categorias e datas quando o resultado vem vazio ou a contagem é zero.
- Verificação da métrica, dos filtros e do período, com checagens determinísticas do formato da evidência e dos números apresentados na resposta.
- Interpretação de meses sem ano em todos os anos disponíveis, com tratamento dos meses incompletos em séries e coortes.
- Contagem de clientes distintos em métricas de pessoas. Na comparação de campanhas, a consulta deve mostrar a contagem que determina a liderança.
- Visualização por tabela, barras ou linhas, respeitando o formato solicitado quando os dados retornados o permitem.
- Histórico de perguntas e respostas na sessão, com interpretação de continuações a partir da última pergunta e exibição da pergunta completa usada na consulta.
- Limites de tempo e linhas para consultas; exemplos de colunas pessoais reconhecidas são omitidos do contexto enviado ao modelo.
- Limites de chamadas ao modelo por pergunta e métricas de duração, tokens e custo estimado quando configurado.

## Melhorias e extensões

- Usar um modelo mais capaz apenas na verificação e medir o acerto com um conjunto maior de perguntas de referência. Com modelos pequenos, perguntas de várias etapas podem variar entre execuções.
- Contexto de mais de uma pergunta e referências aos resultados anteriores; a implementação atual usa apenas a última pergunta interpretada.
- Cache do esquema e seleção das tabelas relevantes, para bancos maiores.
- Melhorar a escolha dos eixos para resultados com mais de três colunas ou múltiplas métricas.
- Exportação do resultado completo, além do limite de linhas carregadas na interface. Os controles atuais permitem baixar os dados carregados na tabela e a imagem do gráfico.
- Controle de recursos para uso em banco compartilhado, além dos limites de linhas e de tempo.
- Versões fixas das dependências, para reproduzir o ambiente testado.
