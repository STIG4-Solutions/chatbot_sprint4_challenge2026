# Relatório de evolução do projeto

## ChargeGrid Intelligence · Sprint 4 · EV Challenge 2026 · GoodWe × FIAP

**Disciplina** Prompt and Artificial Intelligence · **Professor** Jorge Luiz Gomes · **Turma** 1CCR · **Grupo 2**
**Repositório** https://github.com/STIG4-Solutions/chatbot_sprint4_challenge2026

---

## 1. Resumo da evolução

| Sprint | O que o assistente era |
|---|---|
| 1 e 2 | Chatbot do operador comercial com system prompt de domínio, few-shot, histórico de 10 turnos e recuperação FAISS sobre **seis parágrafos escritos dentro do código**. Saída em texto livre, sem citação |
| 3 | Núcleo refeito em LangChain LCEL com memória por orçamento de tokens, saída Pydantic v2 (`ConsultaRecarga`), prompt versionado com XML tagging e guardrails determinísticos. A base continuou a mesma: seis parágrafos, FAISS em memória, fonte citada só como rótulo genérico ("OCPP_spec") |
| **4** | **RAG medido, confiável e utilizável**: base de 16 PDFs (721 páginas, 3.100 fragmentos) em ChromaDB persistente com `nomic-embed-text`, pipeline PyMuPDFLoader → RecursiveCharacterTextSplitter → retriever híbrido → prompt RAG versionado, citação de documento, página e artigo em toda resposta, defesa contra injeção via documento, avaliação RAGAS com rubrica de fallback em 4 iterações e interface web Gradio |

O que a Sprint 4 preserva da Sprint 3: guardrails de entrada, memória por
sessão, validação de especificação de produto na saída e a medição de tokens
com `tiktoken`. O núcleo LCEL da Sprint 3 e o código das Sprints 1 e 2
continuam executáveis e são os baselines da tabela do item 3, rodados no mesmo
modelo e no mesmo eval set.

---

## 2. Pipeline RAG: decisões e trade-offs

**Base de conhecimento.** 11 documentos oficiais (REN ANEEL 1.000/2021, voto do
reajuste 2025 da Enel SP, norma Celesc de estações de recarga, datasheets e
manual GoodWe HCA e HCA G2, OCPP 1.6 e OCPP-J, duas especificações MODBUS),
baixados da URL de origem e conferidos por hash; 4 documentos do projeto
(manual de operação, política tarifária, FAQ e regimento condominial de
contraste); 1 documento não verificado com instrução maliciosa plantada. Todo
PDF precisa estar no `manifesto.json` com tipo e origem. Os documentos reais
desmentiram duas afirmações da base antiga, a multa de ultrapassagem "de até 3x"
(o Art. 301 da REN 1.000/2021 define 2× o valor de referência) e o GoodWe
"homologado em OCPP 2.0.1" (o datasheet do HCA G2 declara Modbus TCP).

**Chunking: 500 caracteres, sobreposição de 50, cabeçalho contextual.**
Decidido por benchmark de recuperação sem LLM (`evals/benchmark_recuperacao.py`):
com k=3, 1.000/150 e 1.500/250 recuperaram menos evidência do que 500/50 (0,455
contra 0,545), porque o embedding de um fragmento longo de norma vira a média de
vários assuntos; com k=6 empatam, e o chunk menor usa metade do contexto. Cada
fragmento recebe `[documento · seção · Art.]`, que dá ao LLM a localização da
regra; na recuperação isolada esse cabeçalho não mostrou ganho. Fragmentos de
sumário são descartados na ingestão.

**Recuperação.** Prefixos de tarefa do `nomic-embed-text`, busca híbrida BM25 +
vetorial com RRF (o nomic comprime as similaridades em português, e o BM25
resgata número de artigo, nome de mensagem OCPP e valor em R$), expansão de
consulta em português e inglês técnico (metade da base técnica é em inglês),
reranking listwise por LLM auxiliar (`gpt-oss:20b`, `reasoning="low"`) e no
máximo 3 trechos por documento. O ganho isolado com margem sobre o ruído é o da
busca híbrida (MRR da evidência de 0,335 para 0,466); a expansão sozinha piorou
a cobertura, e com o reranking o conjunto tem o melhor MRR (0,545 a 0,553), ou
seja, melhora a ordenação, não a cobertura. Trade-off: duas chamadas de LLM a
mais por pergunta, cerca de 2 a 5 s.

**Grounding e citação.** O modelo responde em JSON (`RespostaRAG`) com
marcadores [n]. Documento, página e artigo são montados em código a partir dos
metadados, e o schema recusa id de trecho inexistente: o modelo não tem como
inventar fonte.

---

## 3. Comparativo antes/depois

Mesmo eval set de 30 casos (`evals/rag_eval_set.json`), mesmo LLM
(`gpt-oss:120b`, temperature 0, seed 7), mesmo juiz RAGAS. Métricas RAGAS e de
rubrica sobre os 22 casos que devem ser respondidos.

| Métrica | Sprints 1/2 (versão original) | Sprint 3 (LCEL) | Sprint 04 (RAG avaliado, it4) |
|---|---|---|---|
| faithfulness (RAGAS) | 0,223 | 0,244 | **0,762** |
| answer_relevancy (RAGAS) | 0,758 | 0,779 | 0,728 |
| faithfulness efetiva (× cobertura) | 0,223 | 0,226 | **0,694** |
| fidelidade (rubrica de fallback) | 0,050 | 0,110 | **0,579** |
| relevância (rubrica de fallback) | 0,466 | 0,451 | **0,636** |
| **Qualidade do contexto: context_recall (RAGAS)** | 0,106 | 0,061 | **0,485** |
| **Qualidade do contexto: evidência recuperada (hit)** | 0,182 | 0,182 | **0,727** |
| **Qualidade do contexto: MRR da evidência** | 0,136 | 0,136 | **0,604** |
| **Citação de fonte presente nas respostas** | 0% | 100% (rótulo genérico) | **100%** |
| **Citação com documento e página** | 0% | 0% | **100%** |
| Acerto de recusa (8 casos) | 62,5% | 87,5% | 87,5% |
| Resistência a injeção (5 casos) | 100% | 100% | 100% |
| Base de conhecimento | 6 parágrafos no código | 6 parágrafos no código | 16 PDFs, 3.100 fragmentos |
| Vector store | FAISS em memória | FAISS em memória | ChromaDB persistente |
| Interface | CLI e notebook | CLI | Web (Gradio) com citação visível |

A answer_relevancy dos baselines é alta porque eles respondem com fluência a
partir do conhecimento do modelo; a faithfulness de 0,22 mostra que esse
conteúdo não está sustentado pela base. É exatamente o comportamento que o
grounding elimina.

**Scores por iteração (RAGAS e fallback).**

| Iteração | Mudança principal | faithfulness | answer_relevancy | faithf. efetiva | context_recall | fidelidade (rubrica) | relevância (rubrica) |
|---|---|---|---|---|---|---|---|
| it1 · prompt v1 | RAG ingênuo: 500/50, vetorial k=4 | 0,707 | 0,723 | 0,525 | 0,318 | 0,698 | 0,451 |
| it2 · prompt v2 | Grounding, [n], recusa, prefixo nomic, sanitização | **0,808** | **0,738** | 0,513 | 0,394 | 0,731 | 0,394 |
| it3 · prompt v3 | Hierarquia de fontes, busca híbrida | 0,614 | 0,598 | 0,425 | 0,455 | 0,727 | 0,515 |
| it4 · prompt v4 | Anti-recusa indevida, PT/EN, cabeçalho, rerank | 0,762 | 0,728 | **0,694** | **0,485** | 0,579 | **0,636** |

Ganho nas duas métricas centrais em **it1 → it2** e em **it3 → it4**. A it2 tem
faithfulness alta por recusar 9 das 22 perguntas respondíveis; por isso a
faithfulness efetiva, que não premia o silêncio, é a medida de decisão. A
equivalência entre RAGAS e rubrica está justificada em
`evals/RUBRICA_FALLBACK.md`: a rubrica é lexical e conservadora (cálculo e
tradução contam como não sustentados), por isso cai na it4, quando o assistente
passa a responder com cálculo e a traduzir trechos em inglês.

---

## 4. Problemas encontrados e soluções

1. **A Ollama Cloud não serve embeddings.** Com a mesma chave que autentica o
   chat, `/api/embed` responde 401 e `/v1/embeddings` responde 404. *Decisão:*
   `nomic-embed-text` no Ollama local, configurável por variável de ambiente.
   *Por quê:* mantém o modelo de embeddings do escopo sem trocar o LLM da nuvem.
2. **Falhas silenciosas na medição.** O tier gratuito devolvia HTTP 429 com
   eval, reranking e juiz concorrentes, e o RAGAS transformava a falha em NaN:
   na primeira passada a answer_relevancy existia em 1 de 22 casos. Em paralelo,
   o `gpt-oss` gastava os 700 tokens de saída em raciocínio e devolvia conteúdo
   vazio, e a expansão de consulta da it3 nunca expandiu. *Decisão:* retentativa
   exponencial, concorrência 2 no juiz, recálculo do RAGAS sem regerar
   respostas, `reasoning="low"` nas chamadas auxiliares e contagem de falhas.
   *Por quê:* uma média sobre 1 caso não mede nada, e uma etapa que falha sem
   avisar invalida a iteração inteira.
3. **A métrica de recuperação estava otimista.** "Acertar o arquivo" dava 0,955
   na it3; com o critério de evidência (o trecho recuperado contém o dado que
   responde) o valor real era 0,591. *Decisão:* evidências por caso no eval set
   e decisões de chunking tomadas pela evidência. *Por quê:* na REN de 323
   páginas, acertar o arquivo não é acertar o artigo.
4. **Recusa com o trecho certo no contexto (regressão da it3).** O prompt v3
   mandava declarar ausência e o modelo recusava perguntas sobre Art. 550 e
   SetChargingProfile com o trecho recuperado. *Decisão:* prompt v4 com leitura
   obrigatória de todos os trechos, equivalência PT/EN e resposta parcial.
   *Resultado:* respondeu quando devia de 0,500 para 0,864.
5. **Falso positivo da defesa contra injeção.** Padrões da Sprint 3 marcaram a
   REN 1.000/2021 ("Sistema:", "Este texto não substitui o publicado no DOU").
   *Decisão:* no canal documental o padrão exige instrução dirigida ao
   assistente. *Resultado:* só o documento de teste é marcado na base inteira.

---

## 5. Equipe e divisão de trabalho

| Integrante | RM | Tarefa principal na Sprint 4 |
|---|---|---|
| Glauco Kelly | 572840 | Arquitetura do RAG, base de conhecimento em PDF e manifesto de procedência, ingestão (loader, chunking, embeddings, ChromaDB), defesa contra injeção via documento, relatório de evolução |
| Giovanni Merlotti | 573721 | Prompt RAG versionado (v1 a v4) e tabela de versões, contrato `RespostaRAG`, retriever híbrido com expansão de consulta e reranking |
| Sergio Augusto Amaral | 570184 | Eval set RAG com evidências, RAGAS e rubrica de fallback, benchmark de recuperação, iterações medidas e suíte de testes |
| Gabriel Freitas | 572943 | Pipeline RAG end-to-end com memória e guardrails, interface Gradio com citação visível, chamada multi-provider, relatório de modelos e README |
