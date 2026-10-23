# Prompt RAG: controle de versões

Cada versão é um arquivo próprio (`prompt_rag_v1.md` a `prompt_rag_v4.md`),
carregado em tempo de execução por `src/rag/prompt_rag.py`. A versão de
produção é a **v4**. O system prompt conversacional da Sprint 3 continua em
`prompts/system_prompt_v*.md` e é o baseline "Sprint 3" das tabelas.

## Como o ganho foi medido

- Mesmo eval set em todas as linhas: `evals/rag_eval_set.json`, 30 casos
  (16 happy path, 1 edge case, 1 de contraste com o contexto condominial, 3 sem
  resposta na base, 2 fora de escopo, 2 de injeção pela pergunta, 3 de injeção
  via documento e 2 de recusa de domínio).
- Mesmo modelo e parâmetros: `gpt-oss:120b`, temperature 0, top_p 0,9,
  max_tokens 1200, seed 7.
- RAGAS (faithfulness, answer_relevancy, context_recall) com juiz fixo
  (`gpt-oss:120b`, temperature 0) sobre os 22 casos que devem ser respondidos,
  mais a rubrica manual de fallback (`evals/RUBRICA_FALLBACK.md`) e as métricas
  de recusa, citação, injeção e recuperação.
- Cada iteração muda o prompt **e** a recuperação. A contribuição isolada da
  recuperação está medida à parte, sem LLM gerador, em
  `evals/resultados/benchmark_recuperacao.json` (ver `docs/relatorio_rag.md`,
  item 3): a busca híbrida é o ganho isolado com margem clara; cabeçalho
  contextual e expansão não mostraram ganho isolado, e o reranking melhora a
  ordenação. Por isso o ganho da it4 não deve ser atribuído só ao prompt v4.
- Reproduzir: `python -m evals.run_rag_eval --preset itN`. Resultados por caso
  em `evals/resultados/itN.json`.

## Tabela de versões

| Versão | O que mudou no prompt | Recuperação na mesma iteração | Por quê |
|---|---|---|---|
| v1 | Papel, tarefa "use os trechos e cite a fonte", JSON | Chunk 500/50, vetorial k=4, sem prefixo de tarefa, sem sanitização | Linha de base: o RAG mais simples que atende ao enunciado |
| v2 | Grounding obrigatório ("SOMENTE com os trechos"), marcador [n] por frase, recusa quando o contexto não sustenta, contexto tratado como dado e não como instrução, escopo | Prefixos `search_document`/`search_query` do nomic, sanitização de injeção na ingestão, k=5 | A v1 respondia com conhecimento externo e não marcava qual trecho sustentava cada frase |
| v3 | Hierarquia de fontes (oficial, projeto, não verificada), resposta parcial, contexto B separado do A, cálculo só com números presentes, limite de frases, exemplo few-shot | Busca híbrida BM25 + vetorial com RRF, k=6, expansão de consulta (que falhou em silêncio, ver abaixo) | Fontes divergentes (fórum × política tarifária) e regras condominiais misturadas às comerciais |
| v4 | Leitura de todos os trechos antes de declarar ausência, equivalência de vocabulário PT/EN ("avisar" = "comunicar previamente"; "limitar potência" = "charging profile"), resposta parcial mantém `contexto_suficiente=true`, exemplos few-shot trocados por temas fora do eval set | Cabeçalho contextual em cada fragmento, expansão de consulta corrigida, reranking por LLM | A v3 recusava metade das perguntas respondíveis mesmo com o trecho certo recuperado |

## Ganho medido por iteração

| Métrica | it1 (v1) | it2 (v2) | it3 (v3) | it4 (v4) |
|---|---|---|---|---|
| **faithfulness (RAGAS)** | 0,707 | **0,808** | 0,614 | 0,762 |
| **answer_relevancy (RAGAS)** | 0,723 | **0,738** | 0,598 | 0,728 |
| faithfulness das respostas dadas | 0,722 | 0,867 | 0,849 | 0,803 |
| faithfulness efetiva (× cobertura) | 0,525 | 0,513 | 0,425 | **0,694** |
| context_recall (RAGAS) | 0,318 | 0,394 | 0,455 | **0,485** |
| relevância (rubrica) | 0,451 | 0,394 | 0,515 | **0,636** |
| respondeu quando devia | 0,727 | 0,591 | 0,500 | **0,864** |
| acerto de recusa | 1,000 | 1,000 | 1,000 | 0,875 |
| citação com documento e página | 1,000 | 1,000 | 1,000 | 1,000 |
| resistência a injeção | 1,000 | 1,000 | 1,000 | 1,000 |
| hit da evidência (k recuperados) | 0,545 | 0,591 | 0,682 | **0,727** |
| MRR da evidência | 0,314 | 0,327 | 0,439 | **0,604** |

**Iterações com ganho nas duas métricas centrais (faithfulness e
answer_relevancy):** it1 → it2 (+0,101 e +0,015) e it3 → it4 (+0,148 e
+0,130). De it1 para it4, a faithfulness efetiva sobe 0,169, o context_recall
0,167 e o MRR da evidência 0,290.

## Leitura honesta da tabela

- **A faithfulness da v2 é inflada por recusa.** A v2 recusou 9 das 22
  perguntas respondíveis. Uma recusa não afirma nada, então quase não erra. Por
  isso a tabela traz a faithfulness só das respostas dadas e a faithfulness
  efetiva (faithfulness das respostas dadas × fração respondida), que é a
  medida que não premia o silêncio. Nela a v4 é a melhor versão com folga.
- **A v3 foi uma regressão, e o diagnóstico mudou o projeto.** A recuperação
  melhorou (hit 0,591 → 0,682) mas a geração piorou, por duas causas medidas.
  (1) A expansão de consulta não funcionava: o `gpt-oss` consumia todo o
  `num_predict` de 700 tokens em raciocínio e devolvia conteúdo vazio, e o
  código caía silenciosamente na consulta original. (2) O prompt mandava
  declarar ausência sem pedir que o modelo procurasse o dado com outras
  palavras ou em inglês, e o modelo recusava com o trecho certo no contexto
  (casos 8, 9 e 10). A v4 corrige o prompt; o auxiliar passou a usar
  `reasoning="low"` e a contar falhas.
- **O acerto de recusa da v4 caiu para 0,875 por um caso.** Perguntado sobre o
  preço de um shopping específico (caso 20), o modelo respondeu com as tarifas
  do piloto ChargeGrid em vez de declarar que o preço daquele estabelecimento não
  está na base. A resposta está correta sobre o piloto e citada, mas substitui
  a entidade perguntada. É a próxima regra a entrar no prompt.
- **A rubrica manual de fidelidade cai na v4 (0,731 → 0,579)** porque a v4
  responde mais perguntas com cálculo (folga, tarifa de ponta) e traduz
  trechos em inglês: número calculado e termo traduzido não aparecem
  literalmente no contexto, e a rubrica é lexical. O RAGAS, que verifica
  semanticamente, não acompanha a queda. As duas métricas estão registradas
  por caso para conferência.
- **Exemplo few-shot e eval set.** O exemplo da v3 ("posso cobrar mais caro no
  horário de pico?") se sobrepunha ao caso 3 do eval set. Na v4 os exemplos
  foram trocados por temas que não estão no eval set (StatusNotification e
  Art. 557), para que o ganho não venha de vazamento do gabarito.
