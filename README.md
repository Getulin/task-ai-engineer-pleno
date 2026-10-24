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

O `.env` define o provedor e os limites e é ignorado pelo Git. `LLM_PROVIDER` e `LLM_MODEL` são obrigatórios.

| Variável | Uso |
| --- | --- |
| `LLM_PROVIDER` | `ollama`, `gemini`, `openai` ou `groq` |
| `LLM_MODEL` | Modelo do provedor escolhido |
| `OLLAMA_BASE_URL` | Endereço do Ollama quando `LLM_PROVIDER=ollama`; veja [docs/ollama.md](docs/ollama.md) |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY` | Chave do provedor escolhido |
| `LLM_REQUESTS_PER_SECOND` | Limite de requisições ao provedor; `0.2` na camada gratuita do Gemini |
| `SQL_ROW_LIMIT`, `SQL_TIMEOUT_SECONDS` | Limites por consulta (padrão: 1.000 linhas e 10 s) |

### Testes

```bash
python -m pytest desafio_1/tests -q
```

## Fluxo e arquitetura

```text
pergunta
  → descoberta de tabelas, colunas, relações e valores do SQLite
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
| `schema.py` | Lê o esquema em tempo de execução: tabelas, colunas, relações, valores de colunas de baixa cardinalidade, intervalos de datas e meses cobertos só em parte. Nenhuma consulta é fixa no código. |
| `db.py` | Executa uma instrução `SELECT` ou `WITH` por vez, em conexão somente leitura, com limite de linhas e de tempo. |
| `nodes.py` | Gera, executa, corrige e verifica o SQL; escolhe a visualização e redige a resposta. |
| `llm.py` | Cria o modelo do provedor configurado e repete chamadas recusadas por limite de taxa. |
| `app.py` | Interface Streamlit com resposta, gráfico, avisos e a seção “Etapas e consultas”. |

A verificação classifica cada resultado em três casos: a consulta responde à pergunta; a pergunta admite mais de uma leitura e a consulta aplica uma delas, que passa a ser exibida como premissa; ou há um erro objetivo (métrica, filtro, agrupamento ou período), que gera uma consulta adicional. A nova verificação recebe as correções já pedidas. Se o erro persistir, o resultado aparece com a ressalva em vez de ser descartado.

Os dados vão de 22/07/2024 a 22/07/2025. Séries mensais e coortes excluem os meses incompletos (julho de 2024 e julho de 2025); totais e médias usam todos os registros. Em contagens de meses após um evento, o mês do evento é M0, “mês seguinte” é M+1 e “terceiro mês” é M+3. A resposta informa como termos desse tipo foram interpretados.

Listas aparecem em tabela, comparações em barras e séries temporais em linhas, com uma linha por categoria quando o resultado tem uma dimensão como canal. A interface avisa quando a consulta excede o limite de linhas.

## Consultas testadas

Os resultados abaixo foram conferidos diretamente no banco e estão nos testes de `desafio_1/tests/test_business_questions.py`. O agente os reproduz com `gemini-3.5-flash-lite`.

| Pergunta | Resultado |
| --- | --- |
| Liste os 5 estados com maior número de clientes que compraram via app em maio. | São Paulo 6; Minas Gerais 3; Santa Catarina 3; dois entre Alagoas, Espírito Santo e Paraná, empatados com 2 |
| Quantos clientes interagiram com campanhas de WhatsApp em 2024? | 17 |
| Quais categorias de produto tiveram o maior número de compras em média por cliente? | Roupas 2,21; Viagens 2,16; Livros 1,98 |
| Qual o número de reclamações não resolvidas por canal? | Telefone 19; Chat 18; E-mail 14 |
| Qual a tendência de reclamações por canal no último ano? | Série mensal por canal, de agosto de 2024 a junho de 2025 |
| Qual percentual de cada coorte de primeira compra voltou a comprar no mês seguinte e no terceiro mês? | Agosto de 2024: 43 clientes, 37,21% e 60,47%; setembro: 13 clientes, 69,23% e 38,46% |

## Melhorias e extensões

- Usar um modelo mais capaz apenas na verificação e medir o acerto com um conjunto maior de perguntas de referência. Com modelos pequenos, perguntas de várias etapas podem variar entre execuções.
- Memória de conversa, para perguntas de acompanhamento como “e por estado?”.
- Cache do esquema e seleção das tabelas relevantes, para bancos maiores.
- Exportação do resultado em CSV e do gráfico pela interface.
- Controle de recursos para uso em banco compartilhado, além dos limites de linhas e de tempo.
- Versões fixas das dependências, para reproduzir o ambiente testado.
