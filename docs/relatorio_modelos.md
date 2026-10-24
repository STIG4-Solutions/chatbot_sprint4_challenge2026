# Relatório de uso de modelos e parâmetros · Sprint 4

Comparativo de modelos no pipeline RAG e efeito de `temperature`, `k`, `top_p`
e `max_tokens`. Todos os números vêm de `evals/resultados/*.json`, gerados por
`scripts/reproduzir_avaliacoes.sh`. O relatório de modelos da Sprint 3, sobre o
núcleo conversacional sem RAG, está preservado no histórico Git deste arquivo.

## 1. Método

- **Configuração fixa:** a da iteração 4 (`--preset it4`): prompt RAG v4, chunk
  500/50 com cabeçalho contextual, prefixos do nomic, busca híbrida, expansão de
  consulta, reranking, k=6.
- **Eval set:** os mesmos 30 casos de `evals/rag_eval_set.json`.
- **Juiz RAGAS fixo** (`gpt-oss:120b`, temperature 0) para todos os modelos
  avaliados, inclusive quando o modelo avaliado é o próprio `gpt-oss:120b`. O
  viés de autoavaliação existe; ele é limitado porque o juiz verifica
  afirmações contra o contexto, e não preferência de estilo.
- **Uma passada por configuração**, por limite de cota do tier gratuito. A
  expansão e o reranking usam um LLM auxiliar, e a recuperação varia entre
  passadas mesmo com temperature 0: o hit da evidência variou de 0,636 a 0,727
  entre execuções com o mesmo retriever. Diferenças menores do que cerca de 0,1
  nas métricas que dependem da recuperação não são conclusivas.

## 2. Comparativo de modelos

Todos servidos pela Ollama Cloud, via `ChatOllama`, com os mesmos parâmetros de
geração (temperature 0, top_p 0,9, max_tokens 1200, seed 7).

| Métrica | gpt-oss:120b | gpt-oss:20b | gemma4:31b |
|---|---|---|---|
| Fabricante | OpenAI (open-weight) | OpenAI (open-weight) | Google |
| faithfulness (RAGAS) | 0,762 | 0,715 | **0,785** |
| faithfulness das respostas dadas | 0,803 | 0,775 | **0,933** |
| faithfulness efetiva (× cobertura) | **0,694** | 0,670 | 0,679 |
| answer_relevancy (RAGAS) | 0,728 | **0,765** | 0,617 |
| context_recall (RAGAS) | 0,485 | 0,492 | 0,485 |
| relevância (rubrica) | **0,636** | 0,538 | 0,576 |
| respondeu quando devia | **0,864** | **0,864** | 0,727 |
| acerto de recusa | 0,875 | **1,000** | **1,000** |
| citação com documento e página | **1,000** | 0,947 | **1,000** |
| resistência a injeção | 1,000 | 1,000 | 1,000 |
| erros de contrato (JSON inválido) | **0** | 1 | **0** |
| latência média por pergunta | 9,7 s | 25,3 s | **8,4 s** |

**Escolha: `gpt-oss:120b` como modelo primário.** É o que mais responde sem
perder fidelidade (maior faithfulness efetiva e maior relevância pela rubrica),
não teve erro de contrato e mantém a latência abaixo de 10 s. O `gemma4:31b` é
o mais fiel no que responde (0,933) e o mais rápido, mas recusa mais (respondeu
72,7% das perguntas respondíveis contra 86,4%) e tem a menor answer_relevancy:
é conservador. Fica configurado como `OLLAMA_MODEL_ALT2` e é a alternativa para
um cenário em que errar custa mais do que deixar de responder. O
`gpt-oss:20b` foi o mais lento na nuvem (25 s), teve uma saída fora do
contrato JSON e é o pior em faithfulness; continua como modelo auxiliar da
expansão e do reranking, onde a tarefa é curta e roda com `reasoning="low"`.

**Modelos testados e descartados.** `deepseek-v4.1-flash` e
`mistral-large-3:675b` não concluíram uma resposta do pipeline em 150 s na
sonda de disponibilidade e ficaram fora do comparativo. Na primeira rodada
completa, o `gemma4:31b` manteve o stream aberto sem concluir por mais de uma
hora; o executor do eval passou a ter timeout de 300 s por caso.

## 3. Parâmetros

### temperature = 0 (recomendado pelo escopo e adotado)

Varreduras sem RAGAS (rubrica, recusa, citação e recuperação), para caber na cota do tier gratuito; a linha de base é a it4, com o mesmo modelo.

| Métrica | temperature 0 (it4) | temperature 0,7 |
|---|---|---|
| fidelidade (rubrica) | 0,579 | 0,605 |
| relevância (rubrica) | 0,636 | 0,595 |
| acerto de recusa | 0,875 | 0,875 |
| respondeu quando devia | 0,864 | 0,864 |
| citação com doc. e página | 1,000 | 1,000 |
| hit da evidência | 0,727 | 0,682 |
| MRR da evidência | 0,604 | 0,614 |
| erros de contrato | 0 | 0 |
| tokens de entrada | 1921,5 | 1937,6 |
| latência (s) | 9,702 | 12,866 |

As diferenças são pequenas e em sentidos opostos (fidelidade pela rubrica
+0,026, relevância −0,041, MRR +0,010), dentro da variação entre passadas
observada na recuperação: a amostragem não trouxe ganho consistente, aumentou a
latência e tira a reprodutibilidade. Mantém-se 0.

O RAG deve ser função do contexto recuperado, não da amostragem. Com
temperature 0 a decodificação é gulosa: a mesma pergunta com o mesmo contexto
produz, na prática, a mesma resposta, o que torna as iterações comparáveis.

### top_p = 0,9

Com temperature 0 o `top_p` **não tem efeito**: a decodificação gulosa escolhe
sempre o token mais provável, e o corte de massa de probabilidade só atua
quando há amostragem. O valor 0,9 é mantido para que, se a temperature for
elevada (por exemplo, para variar o estilo na interface), a amostragem já
exclua a cauda de tokens improváveis, que é onde nascem números e nomes
inventados. Por isso não foi feita varredura de `top_p` em temperature 0: ela
mediria ruído.

### k (trechos no contexto) = 6

Varreduras sem RAGAS (rubrica, recusa, citação e recuperação), para caber na cota do tier gratuito; a linha de base é a it4, com o mesmo modelo.

| Métrica | k = 3 | k = 6 (it4) | k = 10 |
|---|---|---|---|
| fidelidade (rubrica) | 0,583 | 0,579 | 0,684 |
| relevância (rubrica) | 0,561 | 0,636 | 0,538 |
| acerto de recusa | 1,000 | 0,875 | 1,000 |
| respondeu quando devia | 0,818 | 0,864 | 0,864 |
| citação com doc. e página | 1,000 | 1,000 | 1,000 |
| hit da evidência | 0,636 | 0,727 | 0,636 |
| MRR da evidência | 0,591 | 0,604 | 0,494 |
| erros de contrato | 0 | 0 | 0 |
| tokens de entrada | 1729,8 | 1921,5 | 2088,3 |
| latência (s) | 10,170 | 9,702 | 9,627 |

Com k=3 o assistente responde menos (81,8%) e cobre menos elementos da
referência: o trecho certo fica de fora do contexto com mais frequência. Com
k=10 a evidência recuperada não aumenta, porque o reranking e o limite de 3
trechos por documento já filtram os candidatos, e o contexto cresce sem trazer
informação nova. A relevância cai porque o modelo passa a misturar trechos
tangenciais. k=6 é o melhor ponto entre cobertura e foco.

### max_tokens (num_predict) = 1200

Varreduras sem RAGAS (rubrica, recusa, citação e recuperação), para caber na cota do tier gratuito; a linha de base é a it4, com o mesmo modelo.

| Métrica | max_tokens 1200 (it4) | max_tokens 250 |
|---|---|---|
| fidelidade (rubrica) | 0,579 | 0,000 |
| relevância (rubrica) | 0,636 | 0,068 |
| acerto de recusa | 0,875 | 0,750 |
| respondeu quando devia | 0,864 | 1,000 |
| citação com doc. e página | 1,000 | 0,000 |
| hit da evidência | 0,727 | 0,682 |
| MRR da evidência | 0,604 | 0,577 |
| erros de contrato | 0 | 24 |
| tokens de entrada | 1921,5 | 1927,2 |
| latência (s) | 9,702 | 19,143 |

Com 250 tokens, 24 dos 30 casos terminam sem JSON válido: o raciocínio do
`gpt-oss` consome o orçamento antes do conteúdo, e o pipeline devolve a
mensagem de erro de contrato. "Respondeu quando devia" sobe para 1,000 só porque
erro de contrato não é contado como recusa, e a relevância cai para 0,068.

O `gpt-oss` é um modelo de raciocínio: parte do `num_predict` é consumida pelo
raciocínio antes do conteúdo. O efeito foi observado diretamente nas chamadas
auxiliares: com 700 tokens e o raciocínio padrão, a expansão de consulta
voltava **vazia** de forma intermitente (na sonda de diagnóstico, as duas
chamadas terminaram com `done_reason=length`, 700 tokens de saída e conteúdo
vazio; com `reasoning="low"` a mesma chamada respondeu em 1,1 s usando 74
tokens). A correção foi `reasoning="low"` e 2.500 tokens nas chamadas
auxiliares; na geração principal, 1.200 tokens cobrem raciocínio e o JSON da
resposta, de cerca de 150 a 300 tokens.

## 4. Bônus: chamada multi-provider (mais de um modelo e mais de um prompt)

`src/multiprovider.py` recupera o contexto **uma vez** e envia a mesma pergunta,
com o mesmo contexto, a todas as combinações de modelo e versão de prompt, em
paralelo. Fixar o contexto isola o efeito de modelo e prompt. A mesma função
alimenta a aba "Comparar modelos e prompts" da interface, e
`evals/comparar_multiprovider.py` mede a matriz em 8 casos do eval set.

Casos 1, 3, 7, 12, 14, 19, 21 e 26 (happy path, sem resposta na base e injeção via documento), 3 modelos × 2 prompts = 48 chamadas, resultados em `evals/resultados/multiprovider.json`.

| Modelo | Fabricante | Prompt | JSON válido | Citação presente | Relevância (rubrica) | Violações | Latência média |
|---|---|---|---|---|---|---|---|
| gpt-oss:120b | OpenAI (open-weight) | v1 | 1,000 | 1,000 | 0,571 | 0 | 18,38 s |
| gpt-oss:120b | OpenAI (open-weight) | v4 | 1,000 | 0,833 | 0,548 | 0 | 12,18 s |
| gpt-oss:20b | OpenAI (open-weight) | v1 | 0,875 | 0,833 | 0,452 | 0 | 13,8 s |
| gpt-oss:20b | OpenAI (open-weight) | v4 | 0,750 | 0,833 | 0,417 | 0 | 15,56 s |
| gemma4:31b | Google | v1 | 1,000 | 1,000 | 0,667 | 0 | 18,11 s |
| gemma4:31b | Google | v4 | 1,000 | 1,000 | 0,667 | 0 | 12,27 s |

**Leitura.** Com o contexto fixo, a versão do prompt muda pouco a relevância
dentro de cada modelo (0,571 contra 0,548 no `gpt-oss:120b`; 0,667 e 0,667 no
`gemma4:31b`): o que a v4 acrescenta é comportamento nos limites, isto é,
grounding, recusa e tratamento de fonte não verificada, e isso aparece no eval
completo (`prompts/rag/VERSIONS.md`), não nesta matriz de 8 casos. O que a
matriz mostra com clareza é a diferença entre modelos: o `gpt-oss:20b` quebra o
contrato JSON em 12,5% a 25% das chamadas, e nenhum modelo, com nenhum prompt,
reproduziu a instrução plantada no fórum (0 violações em 48 chamadas).

**Provedores.** Os modelos são de fabricantes distintos (OpenAI e Google),
servidos pela mesma API da Ollama Cloud. O código também suporta a OpenAI como
segundo provedor (`openai:<modelo>`, via `langchain-openai`), habilitado quando
`OPENAI_API_KEY` está no ambiente. A chave da OpenAI usada nas Sprints 1 e 2
está sem crédito (HTTP 429 `insufficient_quota`), por isso esse provedor não
entrou na medição.
