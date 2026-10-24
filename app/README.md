# Interface web · ChargeGrid Intelligence (Sprint 4)

Interface Gradio sobre o pipeline RAG de `src/rag/`. Cada resposta mostra a
citação da fonte (documento, página e artigo ou seção) no próprio balão do
chat, e o painel lateral exibe o trecho citado, os trechos recuperados com a
relevância de cada um e o diagnóstico do turno.

## Pré-requisitos

1. Dependências instaladas (`pip install -r requirements.txt`) e `.env`
   preenchido com `OLLAMA_API_KEY` (ver README da raiz).
2. Servidor Ollama local com o modelo de embeddings:

   ```bash
   ollama serve &            # se ainda não estiver rodando
   ollama pull nomic-embed-text
   ```

3. Base indexada no ChromaDB persistente (a interface indexa sozinha na
   primeira execução, mas a etapa leva alguns minutos):

   ```bash
   python -m src.rag.ingest
   ```

## Execução

A partir da raiz do repositório:

```bash
python -m app.app
```

Abra http://127.0.0.1:7860. Host e porta podem ser trocados por `APP_HOST` e
`APP_PORT`.

## O que cada aba faz

| Aba | Conteúdo |
|---|---|
| Assistente | Chat com memória por sessão. Resposta com marcadores [n] e lista de fontes. Painel com o trecho citado, tabela de trechos recuperados (relevância, se foi citado, se teve injeção removida), diagnóstico (estágio do pipeline, guardrail, modelo, tokens, latência, memória, consulta reescrita) e configuração (modelo, versão do prompt, k, busca híbrida, expansão, reranking) |
| Comparar modelos e prompts | Chamada multi-provider: a mesma pergunta, com o mesmo contexto recuperado, enviada a vários modelos e versões de prompt em paralelo |
| Base de conhecimento | Documentos indexados, tipo de fonte, número de fragmentos e procedência |

## Comportamentos que a interface deixa visíveis

| Situação | O que aparece |
|---|---|
| Pergunta respondida pela base | Resposta com [n] e lista de fontes; painel com o trecho de cada fonte |
| Informação ausente da base | Declaração de ausência, sem citação e sem especificação inventada |
| Fora de escopo, jailbreak ou injeção na pergunta | Recusa dos guardrails; o diagnóstico mostra que o modelo não foi chamado |
| Documento com instrução embutida | Trecho marcado em "injeção removida"; a instrução não é obedecida |
| Pergunta de continuação ("e no horário de ponta?") | O diagnóstico mostra a pergunta reescrita usada na busca |
