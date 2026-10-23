"""
Consolida os resultados de `evals/resultados/*.json` em tabelas markdown.

    python -m evals.consolidar                 # imprime todas as tabelas
    python -m evals.consolidar --nomes it1 it2 it3

As tabelas de `prompts/rag/VERSIONS.md`, `docs/relatorio_rag.md`,
`docs/relatorio_modelos.md` e do relatório de evolução saem daqui, para que
nenhum número seja digitado à mão.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DIRETORIO = Path(__file__).resolve().parent / "resultados"

COLUNAS = [
    ("ragas_faithfulness", "faithfulness (RAGAS)"),
    ("ragas_faithfulness_respondidas", "faithfulness das respostas dadas"),
    ("faithfulness_efetiva", "faithfulness efetiva (× cobertura)"),
    ("ragas_answer_relevancy", "answer_relevancy (RAGAS)"),
    ("ragas_context_recall", "context_recall (RAGAS)"),
    ("manual_fidelidade", "fidelidade (rubrica)"),
    ("manual_relevancia", "relevância (rubrica)"),
    ("acerto_recusa", "acerto de recusa"),
    ("respondeu_quando_devia", "respondeu quando devia"),
    ("citacao_presente", "citação presente"),
    ("citacao_com_documento_e_pagina", "citação com doc. e página"),
    ("resistencia_injecao", "resistência a injeção"),
    ("hit_evidencia", "hit da evidência"),
    ("mrr_evidencia", "MRR da evidência"),
    ("hit_fonte_esperada", "hit do arquivo esperado"),
    ("erros_de_contrato", "erros de contrato"),
    ("tokens_entrada_medio", "tokens de entrada"),
    ("latencia_media_s", "latência (s)"),
]


def carregar(nome: str) -> dict:
    return json.loads((DIRETORIO / f"{nome}.json").read_text(encoding="utf-8"))


def fmt(valor) -> str:
    if valor is None:
        return "n/a"
    if isinstance(valor, float):
        return f"{valor:.3f}".replace(".", ",") if valor < 50 else f"{valor:.0f}"
    return str(valor)


def tabela(nomes: list[str], colunas=COLUNAS) -> str:
    dados = [carregar(n) for n in nomes]
    linhas = ["| Métrica | " + " | ".join(nomes) + " |", "|---|" + "---|" * len(nomes)]
    for chave, rotulo in colunas:
        linhas.append(f"| {rotulo} | " + " | ".join(fmt(d["agregado"].get(chave)) for d in dados) + " |")
    return "\n".join(linhas)


def por_classe(nome: str) -> str:
    d = carregar(nome)
    classes: dict[str, list] = {}
    for c in d["casos"]:
        classes.setdefault(c["classe"], []).append(c)
    linhas = ["| Classe | casos | faithfulness | fidelidade (rubrica) | recusa correta |", "|---|---|---|---|---|"]
    for classe, casos in sorted(classes.items()):
        f = [c.get("ragas", {}).get("faithfulness") for c in casos if c.get("ragas", {}).get("faithfulness") is not None]
        m = [c["manual"]["fidelidade"] for c in casos if c["manual"]["fidelidade"] is not None]
        r = [c["resultado"]["recusou"] == c["deve_recusar"] for c in casos]
        linhas.append(f"| {classe} | {len(casos)} | {fmt(sum(f)/len(f)) if f else 'n/a'} | "
                      f"{fmt(sum(m)/len(m)) if m else 'n/a'} | {sum(r)}/{len(r)} |")
    return "\n".join(linhas)


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--nomes", nargs="*")
    a.add_argument("--por-classe")
    o = a.parse_args()
    if o.por_classe:
        print(por_classe(o.por_classe))
        return 0
    nomes = o.nomes or sorted(p.stem for p in DIRETORIO.glob("*.json") if p.stem != "benchmark_recuperacao")
    print(tabela(nomes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
