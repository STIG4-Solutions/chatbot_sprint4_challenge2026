"""
Benchmark só de recuperação: hit@k e MRR das fontes esperadas, sem LLM.

Isola a qualidade do retriever da qualidade da geração. É barato (só
embeddings), por isso é o instrumento usado para decidir chunking, prefixo de
tarefa, busca híbrida e k antes de rodar o eval completo com RAGAS.

    python -m evals.benchmark_recuperacao
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from evals.metricas_rag import acerto_evidencia, metricas_recuperacao  # noqa: E402
from src.rag.chunking import EstrategiaChunking  # noqa: E402
from src.rag.retriever import ParametrosRecuperacao, Recuperador  # noqa: E402
from src.rag.vector_store import ConfiguracaoIndice  # noqa: E402

E5, E10, E15 = EstrategiaChunking(500, 50), EstrategiaChunking(1000, 150), EstrategiaChunking(1500, 250)

# (rótulo, estratégia, prefixo, híbrida, expansão, rerank, cabeçalho contextual)
CONFIGURACOES = [
    ("500/50 · sem prefixo · vetorial", E5, False, False, False, False, False),
    ("500/50 · prefixo · vetorial", E5, True, False, False, False, False),
    ("1000/150 · prefixo · vetorial", E10, True, False, False, False, False),
    ("1500/250 · prefixo · vetorial", E15, True, False, False, False, False),
    ("500/50 · prefixo · híbrida", E5, True, True, False, False, False),
    ("500/50 · prefixo · híbrida · cabeçalho", E5, True, True, False, False, True),
    ("500/50 · prefixo · híbrida · cabeçalho · expansão", E5, True, True, True, False, True),
    ("500/50 · prefixo · híbrida · cabeçalho · expansão · rerank", E5, True, True, True, True, True),
]


def main() -> int:
    import argparse

    a = argparse.ArgumentParser()
    a.add_argument("--apenas", nargs="*", help="rótulos de configuração a rodar (mescla com o resultado salvo)")
    o = a.parse_args()
    casos = [c for c in json.loads((RAIZ / "evals" / "rag_eval_set.json").read_text())["casos"]
             if c["fontes_esperadas"] and c.get("evidencias")]
    linhas = []
    destino = RAIZ / "evals" / "resultados" / "benchmark_recuperacao.json"
    anteriores = json.loads(destino.read_text())["linhas"] if o.apenas and destino.exists() else []
    for rotulo, estrategia, prefixo, hibrida, expansao, rerank, cabecalho in CONFIGURACOES:
        if o.apenas and rotulo not in o.apenas:
            linhas.extend(l for l in anteriores if l["configuracao"] == rotulo)
            continue
        for k in (3, 6):
            r = Recuperador(ParametrosRecuperacao(k=k, hibrida=hibrida, expansao=expansao, rerank=rerank),
                            ConfiguracaoIndice(estrategia, prefixo, True, cabecalho))
            buscas = [r.buscar(c["pergunta"]).trechos for c in casos]
            metricas = [metricas_recuperacao([t.metadados["arquivo"] for t in b], c["fontes_esperadas"])
                        for b, c in zip(buscas, casos)]
            evid = [acerto_evidencia([t.documento.page_content for t in b], c["evidencias"]) for b, c in zip(buscas, casos)]
            linha = {"configuracao": rotulo, "k": k,
                     "hit_arquivo": round(statistics.fmean(m["hit"] for m in metricas), 3),
                     "mrr_arquivo": round(statistics.fmean(m["rr"] for m in metricas), 3),
                     "hit_evidencia": round(statistics.fmean(e["hit"] for e in evid), 3),
                     "mrr_evidencia": round(statistics.fmean(e["rr"] for e in evid), 3),
                     "falhas_evidencia": [c["id"] for c, e in zip(casos, evid) if not e["hit"]]}
            linhas.append(linha)
            print(json.dumps(linha, ensure_ascii=False))
    (RAIZ / "evals" / "resultados").mkdir(exist_ok=True)
    destino.write_text(
        json.dumps({"casos_com_fonte_esperada": len(casos), "linhas": linhas}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
