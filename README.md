# Assistente de dados — Desafio 1

Aplicação em Python para responder perguntas de negócio sobre o banco SQLite fornecido no desafio. O usuário faz uma pergunta em português; o agente consulta o esquema do banco, gera SQL, executa a consulta e apresenta a resposta com tabela ou gráfico.

Este repositório implementa o **Desafio 1**. O Desafio 2 não faz parte da entrega de código.

## Executar

Requer Python 3.11 ou superior. A configuração padrão também requer Ollama instalado. O banco de exemplo está em `data/anexo_desafio_1.db`.

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
ollama pull qwen2.5-coder:7b
.\.venv\Scripts\python -m streamlit run desafio_1/app.py
```

### Linux ou macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
ollama pull qwen2.5-coder:7b
.venv/bin/python -m streamlit run desafio_1/app.py
```

O exemplo usa Ollama em `http://localhost:11434`. Também é possível configurar `LLM_PROVIDER` como `gemini`, `openai` ou `groq` no `.env`, junto com a chave do provedor escolhido. O modelo configurado precisa estar disponível no respectivo serviço.

Para usar o modelo Gemini empregado na validação, configure `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-3.5-flash-lite` e `GEMINI_API_KEY` no `.env`. O arquivo `.env` é ignorado pelo Git.

## Fluxo

```text
pergunta
  → descoberta de tabelas, colunas, relações e valores do SQLite
  → geração e execução de SQL
     ├─ erro de SQL: nova tentativa com a mensagem de erro
     └─ resultado vazio: uma reconsideração dos filtros
  → verificação de aderência entre pergunta, SQL e resultado
     └─ resultado insuficiente: até uma consulta adicional
  → escolha de tabela, barras ou linhas
  → resposta e registro das etapas/consultas
```

O grafo está em `desafio_1/agent/graph.py`. `schema.py` inspeciona o banco em tempo de execução e inclui no contexto valores de colunas de baixa cardinalidade e intervalos de datas. `db.py` aceita uma instrução `SELECT` ou `WITH` por vez e abre o SQLite em modo somente leitura. `nodes.py` executa as etapas e registra as consultas e erros que a interface mostra em “Etapas e consultas”.

O fluxo usa até uma consulta adicional após a verificação semântica. Se ela continuar insuficiente, informa que não conseguiu confirmar a resposta. Essa verificação também depende do modelo configurado: ela reduz alguns erros, mas não comprova que toda resposta esteja correta.

## Visualização

Listas aparecem em tabela; comparações podem usar barras; séries temporais podem usar linhas. Em resultados com `mês`, `canal` e uma medida numérica, o gráfico de linhas separa as séries por canal. O usuário pode pedir uma forma de apresentação específica na pergunta, mas a escolha final depende da estrutura retornada e da decisão do modelo.

O limite padrão é de 1.000 linhas por consulta. A interface avisa quando a consulta retornou mais linhas. A síntese em linguagem natural recebe até 50 linhas e é instruída a identificar uma resposta baseada em amostra.

## Verificação

```bash
python -m pytest desafio_1/tests -q
```

Na revisão desta entrega, **30 testes passaram**. Eles cobrem acesso ao banco, proteção contra escrita, reparo de SQL, revisão de uma consulta válida porém incompleta, descarte de resultados antigos após falha, visualização por canal e consultas de referência para as cinco perguntas do enunciado. Valores conferidos diretamente no banco:

| Pergunta | Resultado de referência |
| --- | --- |
| Estados com mais clientes que compraram pelo app em maio | São Paulo 6; Minas Gerais 3; Santa Catarina 3; Alagoas 2; Espírito Santo 2 |
| Clientes que interagiram com WhatsApp em 2024 | 17 |
| Compras por cliente, por categoria | Roupas 2,21; Viagens 2,16 no topo |
| Reclamações não resolvidas por canal | Telefone 19; Chat 18; E-mail 14 |
| Tendência de reclamações por canal no último ano dos dados | Série mensal por canal, de julho de 2024 a julho de 2025 |

Na validação de 23/10/2026, as cinco perguntas foram executadas uma vez com `gemini-3.5-flash-lite`. SQL, linhas retornadas, resposta e visualização foram comparados com as consultas de referência; os cinco resultados foram compatíveis. Na primeira pergunta, três estados empataram com dois clientes; qualquer dois deles completam legitimamente o grupo de cinco. Na quinta, a consulta retornou 38 linhas de mês e canal, exibidas em linhas separadas por canal. Essa execução única confirma o fluxo com um provedor real, mas não mede a taxa de acerto em outras perguntas ou execuções.

## Limites e próximos passos

- A revisão semântica usa o mesmo LLM que gera SQL; uma avaliação com perguntas adicionais e respostas de referência é necessária para medir acerto.
- A descoberta do esquema percorre o banco a cada pergunta. Cache e seleção de tabelas seriam úteis em bases maiores.
- O limite de linhas evita respostas excessivas, mas consultas custosas ainda precisam de limite de tempo e controle de recursos.
- As dependências têm versões mínimas em `requirements.txt`; um arquivo de versões fixas facilitaria repetir o ambiente testado.
