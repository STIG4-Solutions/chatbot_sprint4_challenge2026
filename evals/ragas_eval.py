"""
Avaliação RAGAS (Aula 07): faithfulness, answer_relevancy e context_recall.

Juiz: `gpt-oss:120b` na Ollama Cloud, temperature 0, fixo em todas as
iterações e em todos os modelos comparados, para que a variação de nota venha
do sistema avaliado e não do avaliador. Embeddings do answer_relevancy:
`nomic-embed-text` sem prefixo de tarefa, porque a métrica compara a pergunta
original com perguntas geradas, ou seja, consulta com consulta.

- faithfulness: fração das afirmações da resposta sustentadas pelo contexto.
- answer_relevancy: similaridade entre a pergunta e perguntas que o juiz gera a
  partir da resposta; penaliza resposta evasiva ou fora do assunto.
- context_recall: fração das afirmações da referência presentes no contexto
  recuperado; mede a qualidade da recuperação, independentemente da geração.
"""

from __future__ import annotations

import math
import warnings

warnings.filterwarnings("ignore")

from ragas import EvaluationDataset, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import Faithfulness, LLMContextRecall, ResponseRelevancy  # noqa: E402
from ragas.run_config import RunConfig  # noqa: E402

from src.chain.builder import criar_llm  # noqa: E402
from src.config import ParametrosModelo, carregar_configuracao  # noqa: E402
from src.rag.embeddings import criar_embeddings  # noqa: E402

MODELO_JUIZ = "gpt-oss:120b"


def avaliar_ragas(amostras: list[dict], workers: int = 2) -> list[dict]:
    """Recebe dicts com user_input, response, retrieved_contexts e reference."""
    if not amostras:
        return []
    configuracao = carregar_configuracao()
    juiz = LangchainLLMWrapper(
        criar_llm(ParametrosModelo(modelo=MODELO_JUIZ, temperature=0.0, num_predict=3000, seed=7), configuracao)
    )
    embeddings = LangchainEmbeddingsWrapper(criar_embeddings(configuracao, com_prefixo=False))
    resultado = evaluate(
        EvaluationDataset.from_list(amostras),
        metrics=[Faithfulness(), ResponseRelevancy(), LLMContextRecall()],
        llm=juiz,
        embeddings=embeddings,
        # Concorrência baixa e retentativa longa: o tier gratuito da Ollama
        # Cloud recusa requisições simultâneas (HTTP 429), e uma métrica que
        # falha vira NaN silencioso no RAGAS. Ver docs/relatorio_rag.md.
        run_config=RunConfig(max_workers=workers, timeout=300, max_retries=10, max_wait=90),
        show_progress=False,
    )
    linhas = resultado.to_pandas().to_dict(orient="records")
    saida = []
    for linha in linhas:
        saida.append({
            chave: (None if valor is None or (isinstance(valor, float) and math.isnan(valor)) else float(valor))
            for chave, valor in linha.items()
            if chave in ("faithfulness", "answer_relevancy", "context_recall")
        })
    return saida
