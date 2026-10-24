# Rodar com Ollama

O Ollama executa o modelo localmente, sem chave de API.

## 1. Instalar

Siga as instruções para o seu sistema em <https://ollama.com/download>. Com o serviço ativo, este comando lista os modelos instalados:

```bash
ollama list
```

O serviço escuta em `http://localhost:11434`.

## 2. Baixar um modelo

Escolha um modelo em <https://ollama.com/library> e baixe-o:

```bash
ollama pull <modelo>
```

## 3. Configurar o `.env`

```env
LLM_PROVIDER=ollama
LLM_MODEL=<modelo>
OLLAMA_BASE_URL=http://localhost:11434
```

Depois, inicie a aplicação como descrito no [README](../README.md#execução).

## Modelo testado

O provedor Ollama foi testado com `qwen2.5-coder:7b`. Nas perguntas de referência, esse modelo às vezes omite um filtro, e a verificação, feita pelo mesmo modelo, nem sempre percebe. Para resultados mais consistentes, use um modelo maior.
