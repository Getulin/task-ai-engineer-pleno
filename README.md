# Assistente de dados — Desafio 1

Aplicação em Python para responder perguntas de negócio sobre o banco SQLite fornecido no desafio. O usuário faz uma pergunta em português; o agente consulta o esquema do banco, gera SQL, executa a consulta e apresenta a resposta com tabela ou gráfico, junto com as consultas executadas.

Este repositório implementa o **Desafio 1**. O Desafio 2 não faz parte da entrega de código.

## Execução

Requer Python 3.11 ou superior. O banco de exemplo está em `data/anexo_desafio_1.db`. Antes de rodar, defina o provedor de LLM no `.env` (veja [Configuração](#configuração)). Para rodar localmente sem chave de API, veja [docs/ollama.md](docs/ollama.md).

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

| Variável | Uso |
| --- | --- |
| `LLM_PROVIDER` | `ollama`, `gemini`, `openai` ou `groq` |
| `LLM_MODEL` | Modelo do provedor escolhido |
| `LLM_TEMPERATURE` | Temperatura solicitada ao modelo (padrão: `0`; alguns modelos ignoram esse parâmetro) |
| `OLLAMA_BASE_URL` | Endereço do Ollama quando `LLM_PROVIDER=ollama`; veja [docs/ollama.md](docs/ollama.md) |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY` | Chave do provedor escolhido |
| `DB_PATH` | Caminho do SQLite, relativo à raiz do projeto ou absoluto (padrão: `data/anexo_desafio_1.db`) |
| `LLM_REQUESTS_PER_SECOND` | Limite local de chamadas ao modelo; `0` desativa. Ajuste conforme a cota da sua conta. |
| `SQL_MAX_REPAIR_ATTEMPTS` | Número máximo de execuções com erro antes de desistir (padrão: `3`) |
| `SQL_ROW_LIMIT`, `SQL_TIMEOUT_SECONDS` | Limites por consulta (padrão: 1.000 linhas e 10 s) |

### Testes

```powershell
.\.venv\Scripts\python -m pytest desafio_1/tests -q
```

No Linux ou macOS, use `.venv/bin/python -m pytest desafio_1/tests -q`.

## Fluxo e arquitetura

```text
pergunta
  → continuação: reescrita com a última pergunta interpretada
     └─ continuação dependente sem referência ou leitura incerta: pede esclarecimento
  → descoberta de tabelas, colunas, relações e valores do SQLite
  → interpretação do período citado
     └─ "clientes em um mês" sem evento definido: pede esclarecimento
  → geração e execução de SQL
     ├─ erro de SQL: nova tentativa com a mensagem de erro
     └─ resultado vazio: uma reconsideração dos filtros
  → verificação de aderência entre pergunta, SQL e resultado
     ├─ leitura ambígua: segue com a premissa declarada
     └─ erro objetivo: até uma consulta adicional; se persistir, resposta com ressalva
  → escolha de tabela, barras ou linhas
  → resposta e registro das etapas/consultas
```

O agente é um grafo de estados em LangGraph (`desafio_1/agent/graph.py`). O grafo deixa explícitos os pontos em que o agente volta a gerar SQL e limita quantas vezes isso acontece, o que mantém o comportamento previsível e cada etapa visível na interface.

| Módulo | Responsabilidade |
| --- | --- |
| `schema.py` | Lê o esquema em tempo de execução: tabelas, colunas, relações, valores de colunas de baixa cardinalidade, intervalos de datas e meses cobertos só em parte. Exemplos de colunas pessoais reconhecidas são omitidos do contexto do modelo. |
| `context.py` | Identifica mensagens que dependem da pergunta anterior. |
| `temporal.py` | Interpreta os meses citados na pergunta e identifica quando falta definir o evento que associa clientes a um mês. |
| `db.py` | Executa uma instrução `SELECT` ou `WITH` por vez, em conexão somente leitura, com limite de linhas e de tempo. |
| `nodes.py` | Gera, executa, corrige e verifica o SQL; escolhe a visualização e redige a resposta. |
| `llm.py` | Cria o modelo do provedor configurado e repete chamadas recusadas por limite de taxa. |
| `app.py` | Interface Streamlit com resposta, gráfico, avisos, histórico da sessão e a seção “Etapas e consultas”. Envia a última pergunta interpretada para resolver continuações. |

A verificação classifica cada resultado em três casos: a consulta responde à pergunta; a pergunta admite mais de uma leitura e a consulta aplica uma delas, que passa a ser exibida como premissa; ou há um erro objetivo (métrica, filtro, agrupamento ou período), que gera uma consulta adicional. A nova verificação recebe as correções já pedidas. Se o erro persistir, o resultado aparece com a ressalva em vez de ser descartado.

As consultas de negócio do agente são geradas em tempo de execução. O código usa SQL fixo para inspecionar o esquema, e os testes contêm consultas de referência. O agente omite exemplos de colunas pessoais reconhecidas no esquema e mascara resultados quando o nome da coluna é reconhecido como pessoal. Esse filtro baseado em nomes não cobre aliases ou expressões que incluam dados pessoais. A tabela exibida localmente mantém os valores originais.

As datas do banco vão, em conjunto, de 22/07/2024 a 22/07/2025; o intervalo varia entre as tabelas. O agente recebe a orientação de excluir meses incompletos de séries mensais e coortes (julho de 2024 e julho de 2025) e de incluir todos os registros em totais e médias. Um mês citado pelo nome sem ano abrange todas as ocorrências desse mês nos anos disponíveis; “mais recente” ou um ano explícito alteram esse recorte. Em contagens após um evento, o mês do evento é M0, “mês seguinte” é M+1 e “terceiro mês” é M+3. O verificador confere o SQL gerado, mas a correção da resposta ainda depende do modelo.

O agente escolhe entre tabela, barras e linhas conforme a pergunta e as colunas retornadas. A interface avisa quando a consulta excede o limite de linhas. O histórico mantém perguntas e resultados visíveis durante a sessão. Uma continuação como “e por estado?” usa a última pergunta interpretada para formar uma consulta completa; a interpretação aparece na interface. Perguntas independentes não usam esse contexto, e resultados anteriores não são reenviados ao modelo nessa etapa.

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

## Melhorias realizadas

- Consultas SQL com tentativa de correção após erro, reconsideração de resultados vazios e verificação da métrica, dos filtros e do período antes da resposta.
- Interpretação de meses sem ano em todos os anos disponíveis, com tratamento dos meses incompletos em séries e coortes.
- Contagem de clientes distintos em métricas de pessoas. Na comparação de campanhas, a consulta deve mostrar a contagem que determina a liderança.
- Histórico de perguntas e respostas na sessão, com interpretação de continuações a partir da última pergunta e exibição da pergunta completa usada na consulta.
- Limites de tempo e linhas para consultas; exemplos de colunas pessoais reconhecidas são omitidos do contexto enviado ao modelo.

## Melhorias e extensões

- Usar um modelo mais capaz apenas na verificação e medir o acerto com um conjunto maior de perguntas de referência. Com modelos pequenos, perguntas de várias etapas podem variar entre execuções.
- Contexto de mais de uma pergunta e referências aos resultados anteriores; a implementação atual usa apenas a última pergunta interpretada.
- Cache do esquema e seleção das tabelas relevantes, para bancos maiores.
- Aplicar de forma determinística o tipo de visualização quando o usuário pedir tabela ou gráfico específico.
- Exportação do resultado completo, além do limite de linhas carregadas na interface. Os controles atuais permitem baixar os dados carregados na tabela e a imagem do gráfico.
- Controle de recursos para uso em banco compartilhado, além dos limites de linhas e de tempo.
- Versões fixas das dependências, para reproduzir o ambiente testado.
