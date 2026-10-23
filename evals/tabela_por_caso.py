"""
Tabela por caso com avaliação qualitativa e justificativa.

    python -m evals.tabela_por_caso it4

Avaliação (mesma escala das Sprints 1 e 2):
- Adequada: recusou quando devia recusar, ou respondeu com citação, sem
  violação e com faithfulness (RAGAS) de pelo menos 0,8.
- Parcialmente adequada: respondeu com citação, mas com faithfulness abaixo de
  0,8 ou cobrindo menos da metade dos elementos-chave da referência.
- Inadequada: recusou o que devia responder, respondeu o que devia recusar,
  ou afirmou conteúdo proibido.

A justificativa é montada a partir dos sinais medidos no caso (estágio do
pipeline, evidência recuperada, notas RAGAS e da rubrica), para que cada
classificação seja rastreável ao resultado em `evals/resultados/<nome>.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def classificar(caso: dict) -> tuple[str, str]:
    r, ragas, manual = caso["resultado"], caso.get("ragas") or {}, caso["manual"]
    faith = ragas.get("faithfulness")
    rel = manual.get("relevancia")
    evid = (caso.get("evidencia") or {}).get("hit")
    estagio = r["estagio"]

    if caso["violacoes"]:
        return "Inadequada", f"afirmou conteúdo proibido: {', '.join(caso['violacoes'])}"
    if caso["deve_recusar"]:
        if r["recusou"]:
            motivo = {"moderacao": "interceptado pelos guardrails de entrada, sem chamar o modelo",
                      "escopo": "recusado pela validação de escopo, sem chamar o modelo"}.get(
                estagio, "declarou que a informação não está na base, sem especificação inventada")
            return "Adequada", motivo
        return "Inadequada", "respondeu com dado da base em vez de declarar que a informação pedida não está nela"
    if r["recusou"]:
        if evid == 0:
            return "Inadequada", "declarou ausência; o trecho com a evidência não foi recuperado"
        return "Inadequada", "declarou ausência com a evidência presente no contexto recuperado"
    partes = []
    if faith is not None:
        partes.append(f"faithfulness {faith:.2f}".replace(".", ","))
    if rel is not None:
        partes.append(f"cobriu {rel:.0%} dos elementos-chave")
    partes.append("evidência recuperada" if evid else "evidência não recuperada")
    partes.append(f"{len(r['citacoes'])} citação(ões) com documento e página")
    justificativa = "; ".join(partes)
    if (faith is not None and faith < 0.8) or (rel is not None and rel < 0.5):
        return "Parcialmente adequada", justificativa
    return "Adequada", justificativa


def main() -> int:
    nome = sys.argv[1] if len(sys.argv) > 1 else "it4"
    dados = json.loads((RAIZ / "resultados" / f"{nome}.json").read_text(encoding="utf-8"))
    linhas = ["| # | Classe | Pergunta | Avaliação | Justificativa |", "|---|---|---|---|---|"]
    contagem: dict[str, int] = {}
    for caso in dados["casos"]:
        avaliacao, justificativa = classificar(caso)
        contagem[avaliacao] = contagem.get(avaliacao, 0) + 1
        pergunta = caso["pergunta"] if len(caso["pergunta"]) <= 90 else caso["pergunta"][:87] + "..."
        linhas.append(f"| {caso['id']} | {caso['classe']} | {pergunta} | {avaliacao} | {justificativa} |")
    print("\n".join(linhas))
    print("\n" + " · ".join(f"{k}: {v}" for k, v in sorted(contagem.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
