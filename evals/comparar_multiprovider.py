"""
Bônus da Sprint 4: chamada multi-provider, mais de um modelo e mais de um prompt.

Para cada pergunta, o contexto é recuperado uma vez e enviado a todas as
combinações de modelo e versão de prompt (`src/multiprovider.py`). Como o
contexto é o mesmo, a diferença entre células mede só modelo e prompt.

    python -m evals.comparar_multiprovider
    python -m evals.comparar_multiprovider --modelos gpt-oss:120b gemma4:31b --prompts v1 v3

Métricas por célula (determinísticas, `evals/metricas_rag.py`): JSON válido no
contrato RespostaRAG, citação presente, relevância pela rubrica, violação de
conteúdo proibido e latência.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from evals.metricas_rag import relevancia_manual, violacoes  # noqa: E402
from src.multiprovider import consultar_matriz, fabricante  # noqa: E402
from src.rag.retriever import ParametrosRecuperacao, Recuperador  # noqa: E402

MODELOS_PADRAO = ["gpt-oss:120b", "gpt-oss:20b", "gemma4:31b"]
PROMPTS_PADRAO = ["v1", "v4"]
CASOS_PADRAO = [1, 3, 7, 12, 14, 19, 21, 26]


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--modelos", nargs="*", default=MODELOS_PADRAO)
    a.add_argument("--prompts", nargs="*", default=PROMPTS_PADRAO)
    a.add_argument("--ids", nargs="*", type=int, default=CASOS_PADRAO)
    o = a.parse_args()

    casos = [c for c in json.loads((RAIZ / "evals" / "rag_eval_set.json").read_text())["casos"] if c["id"] in o.ids]
    recuperador = Recuperador(ParametrosRecuperacao())
    celulas = []
    for caso in casos:
        for linha in consultar_matriz(caso["pergunta"], o.modelos, o.prompts, recuperador):
            texto = linha["resposta"]
            celulas.append({
                "caso": caso["id"], "classe": caso["classe"], **linha,
                "relevancia": None if caso["deve_recusar"] else relevancia_manual(texto, caso["criterios"]),
                "citou": bool(linha["citacoes"]),
                "violacoes": violacoes(texto, caso.get("proibidos", [])),
            })
            print(f"caso {caso['id']:>2} · {linha['modelo']:<22} · {linha['prompt']} · válida={linha['valida']} · {linha['latencia_s']} s")

    resumo = []
    for modelo in o.modelos:
        for versao in o.prompts:
            sel = [c for c in celulas if c["modelo"] == modelo and c["prompt"] == versao]
            if not sel:
                continue
            rel = [c["relevancia"] for c in sel if c["relevancia"] is not None]
            respondiveis = [c for c in sel if c["classe"] not in ("sem_resposta",)]
            resumo.append({
                "modelo": modelo, "fabricante": fabricante(modelo), "prompt": versao,
                "json_valido": round(statistics.fmean(c["valida"] for c in sel), 3),
                "citacao_presente": round(statistics.fmean(c["citou"] for c in respondiveis), 3) if respondiveis else None,
                "relevancia_rubrica": round(statistics.fmean(rel), 3) if rel else None,
                "violacoes": sum(bool(c["violacoes"]) for c in sel),
                "latencia_media_s": round(statistics.fmean(c["latencia_s"] for c in sel), 2),
            })
    saida = {"modelos": o.modelos, "prompts": o.prompts, "casos": o.ids, "resumo": resumo, "celulas": celulas}
    destino = RAIZ / "evals" / "resultados" / "multiprovider.json"
    destino.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=1), flush=True)
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
