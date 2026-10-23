"""
Executor do eval RAG da Sprint 4.

Roda o eval set (`evals/rag_eval_set.json`) sobre uma arquitetura e grava os
resultados por caso e agregados em `evals/resultados/<nome>.json`.

Arquiteturas:
    sprint2   núcleo manual das Sprints 1/2 (legacy/), mesma base de seis parágrafos
    sprint3   núcleo LCEL da Sprint 3 (FAISS em memória, prompt v3, ConsultaRecarga)
    rag       pipeline da Sprint 4 (ChromaDB, nomic-embed-text, prompt RAG versionado)

Iterações pré-definidas (ver prompts/rag/VERSIONS.md):
    python -m evals.run_rag_eval --preset sprint2
    python -m evals.run_rag_eval --preset sprint3
    python -m evals.run_rag_eval --preset it1
    python -m evals.run_rag_eval --preset it2
    python -m evals.run_rag_eval --preset it3
    python -m evals.run_rag_eval --preset it4

Qualquer parâmetro do preset pode ser sobrescrito na linha de comando, o que é
usado pelas varreduras de chunking, k, temperature e modelo.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from evals.metricas_rag import (  # noqa: E402
    acerto_evidencia,
    fidelidade_manual,
    metricas_recuperacao,
    parece_recusa,
    relevancia_manual,
    violacoes,
)
from src.config import ParametrosModelo, carregar_configuracao  # noqa: E402

ARQUIVO_EVAL = RAIZ / "evals" / "rag_eval_set.json"
DIRETORIO_RESULTADOS = RAIZ / "evals" / "resultados"
SEED_EVAL = 7
TEMPO_MAXIMO_POR_CASO_S = 300

PRESETS = {
    "sprint2": {"arquitetura": "sprint2"},
    "sprint3": {"arquitetura": "sprint3"},
    "it1": {"arquitetura": "rag", "prompt": "v1", "chunk": 500, "overlap": 50, "k": 4,
            "prefixo": False, "sanitizar": False, "cabecalho": False, "hibrida": False, "limiar": 0.0},
    "it2": {"arquitetura": "rag", "prompt": "v2", "chunk": 500, "overlap": 50, "k": 5,
            "prefixo": True, "sanitizar": True, "cabecalho": False, "hibrida": False, "limiar": 0.0},
    "it3": {"arquitetura": "rag", "prompt": "v3", "chunk": 500, "overlap": 50, "k": 6,
            "prefixo": True, "sanitizar": True, "cabecalho": False, "hibrida": True, "expansao": True,
            "rerank": False, "limiar": 0.0},
    "it4": {"arquitetura": "rag", "prompt": "v4", "chunk": 500, "overlap": 50, "k": 6,
            "prefixo": True, "sanitizar": True, "cabecalho": True, "hibrida": True, "expansao": True,
            "rerank": True, "limiar": 0.0},
}

PADROES = {"prompt": "v3", "chunk": 500, "overlap": 50, "k": 6, "prefixo": True,
           "sanitizar": True, "cabecalho": True, "hibrida": True, "expansao": False, "rerank": False, "limiar": 0.0,
           "modelo": None,
           "temperature": 0.0, "top_p": 0.9, "max_tokens": 1200, "guardrails": True}


# ---------------------------------------------------------------------------
# Execução por arquitetura
# ---------------------------------------------------------------------------

def _executor_rag(cfg: dict):
    from src.rag.chunking import EstrategiaChunking
    from src.rag.pipeline import AssistenteRAG
    from src.rag.retriever import ParametrosRecuperacao, Recuperador
    from src.rag.vector_store import ConfiguracaoIndice

    configuracao = carregar_configuracao()
    indice = ConfiguracaoIndice(EstrategiaChunking(cfg["chunk"], cfg["overlap"]), cfg["prefixo"], cfg["sanitizar"],
                                cfg["cabecalho"])
    recuperador = Recuperador(
        ParametrosRecuperacao(k=cfg["k"], limiar_relevancia=cfg["limiar"], hibrida=cfg["hibrida"],
                              expansao=cfg["expansao"], rerank=cfg["rerank"]), indice
    )
    if cfg["hibrida"]:
        recuperador._indice_lexical()  # inicializa antes das threads
    parametros = ParametrosModelo(
        modelo=cfg["modelo"] or configuracao.modelo_primario, temperature=cfg["temperature"],
        top_p=cfg["top_p"], num_predict=cfg["max_tokens"], seed=SEED_EVAL,
    )
    assistente = AssistenteRAG(cfg["prompt"], parametros, recuperador=recuperador,
                               configuracao=configuracao, com_guardrails=cfg["guardrails"])

    def executar(caso: dict) -> dict:
        r = assistente.responder(caso["pergunta"], session_id=f"eval-{caso['id']}")
        e = r.estruturado
        recusou = r.estagio in ("moderacao", "escopo", "sem_contexto", "validacao_da_resposta") or (
            e is not None and (not e.dentro_do_escopo or not e.contexto_suficiente)
        )
        return {
            "texto": r.texto, "contextos": r.contextos, "recusou": recusou, "estagio": r.estagio,
            "citacoes": [c.rotulo() for c in r.citacoes],
            "citacao_localizada": bool(r.citacoes) and all(c.documento and c.pagina for c in r.citacoes),
            "arquivos_recuperados": [t.metadados.get("arquivo") for t in r.recuperacao.trechos] if r.recuperacao else [],
            "melhor_relevancia": r.recuperacao.melhor_relevancia if r.recuperacao else None,
            "erro": r.erro, "tokens_entrada": r.medicao.tokens_entrada,
            "tokens_saida": r.medicao.tokens_saida, "latencia_s": r.medicao.como_dicionario()["latencia_segundos"],
        }
    return executar, parametros


def _executor_sprint3(cfg: dict):
    from src.assistente import ChargeGridAssistente
    from src.rag.knowledge_base import construir_indice

    configuracao = carregar_configuracao()
    parametros = ParametrosModelo(modelo=cfg["modelo"] or configuracao.modelo_primario,
                                  temperature=cfg["temperature"], top_p=cfg["top_p"], num_predict=1400, seed=SEED_EVAL)
    assistente = ChargeGridAssistente("v3", parametros, configuracao)

    def executar(caso: dict) -> dict:
        r = assistente.responder(caso["pergunta"], session_id=f"eval-{caso['id']}")
        contextos = [d.page_content for d in construir_indice().similarity_search(caso["pergunta"], k=3)]
        e = r.estruturado
        return {
            "texto": r.texto, "contextos": contextos,
            "recusou": r.interceptado or (e is not None and not e.dentro_do_escopo) or parece_recusa(r.texto),
            "estagio": r.estagio, "citacoes": list(e.fontes) if e else [], "citacao_localizada": False,
            "arquivos_recuperados": [], "melhor_relevancia": None, "erro": r.erro_de_schema,
            "tokens_entrada": r.medicao.tokens_entrada, "tokens_saida": r.medicao.tokens_saida,
            "latencia_s": r.medicao.como_dicionario()["latencia_segundos"],
        }
    return executar, parametros


def _executor_sprint2(cfg: dict):
    from evals.legacy_adapter import ChatbotLegadoAdaptado
    from src.chain.builder import criar_llm

    configuracao = carregar_configuracao()
    parametros = ParametrosModelo(modelo=cfg["modelo"] or configuracao.modelo_primario,
                                  temperature=cfg["temperature"], top_p=cfg["top_p"], num_predict=1400, seed=SEED_EVAL)
    llm = criar_llm(parametros, configuracao)

    def executar(caso: dict) -> dict:
        bot = ChatbotLegadoAdaptado(llm)
        contexto = bot._recuperar_contexto(caso["pergunta"])
        texto, medicao = bot.conversar(caso["pergunta"])
        return {
            "texto": texto, "contextos": [c for c in contexto.split("\n\n") if c.strip()],
            "recusou": parece_recusa(texto), "estagio": "legado", "citacoes": [], "citacao_localizada": False,
            "arquivos_recuperados": [], "melhor_relevancia": None, "erro": None,
            "tokens_entrada": medicao.tokens_entrada, "tokens_saida": medicao.tokens_saida,
            "latencia_s": medicao.como_dicionario()["latencia_segundos"],
        }
    return executar, parametros


def _resultado_de_falha(erro: str) -> dict:
    return {
        "texto": "", "contextos": [], "recusou": True, "estagio": "falha_de_execucao", "citacoes": [],
        "citacao_localizada": False, "arquivos_recuperados": [], "melhor_relevancia": None, "erro": erro,
        "tokens_entrada": 0, "tokens_saida": 0, "latencia_s": float(TEMPO_MAXIMO_POR_CASO_S),
    }


# ---------------------------------------------------------------------------
# Agregação
# ---------------------------------------------------------------------------

def _media(valores) -> float | None:
    v = [x for x in valores if x is not None]
    return round(statistics.fmean(v), 4) if v else None


def agregar(casos: list[dict]) -> dict:
    responder = [c for c in casos if not c["deve_recusar"]]
    recusar = [c for c in casos if c["deve_recusar"]]
    respondidos = [c for c in responder if not c["resultado"]["recusou"]]
    injecao = [c for c in casos if c["classe"].startswith("injecao")]
    return {
        "casos": len(casos),
        "ragas_faithfulness": _media(c.get("ragas", {}).get("faithfulness") for c in responder),
        "ragas_answer_relevancy": _media(c.get("ragas", {}).get("answer_relevancy") for c in responder),
        # Faithfulness só das respostas efetivamente dadas: uma recusa indevida
        # ("não está na base") não afirma nada e infla ou derruba a média sem
        # medir fidelidade. A cobertura é reportada ao lado.
        "ragas_faithfulness_respondidas": _media(c.get("ragas", {}).get("faithfulness") for c in respondidos),
        "faithfulness_efetiva": (
            round(_media(c.get("ragas", {}).get("faithfulness") for c in respondidos) * len(respondidos) / len(responder), 4)
            if respondidos and responder and _media(c.get("ragas", {}).get("faithfulness") for c in respondidos) is not None
            else None
        ),
        "ragas_context_recall": _media(c.get("ragas", {}).get("context_recall") for c in responder),
        "manual_fidelidade": _media(c["manual"]["fidelidade"] for c in responder),
        "manual_relevancia": _media(c["manual"]["relevancia"] for c in responder),
        "acerto_recusa": _media(float(c["resultado"]["recusou"]) for c in recusar),
        "respondeu_quando_devia": _media(float(not c["resultado"]["recusou"]) for c in responder),
        "citacao_presente": _media(float(bool(c["resultado"]["citacoes"])) for c in respondidos),
        "citacao_com_documento_e_pagina": _media(float(c["resultado"]["citacao_localizada"]) for c in respondidos),
        "resistencia_injecao": _media(float(not c["violacoes"]) for c in injecao),
        "casos_com_violacao": sum(1 for c in casos if c["violacoes"]),
        "hit_evidencia": _media(c.get("evidencia", {}).get("hit") for c in responder),
        "mrr_evidencia": _media(c.get("evidencia", {}).get("rr") for c in responder),
        "hit_fonte_esperada": _media(c["recuperacao"]["hit"] for c in responder),
        "mrr_fonte_esperada": _media(c["recuperacao"]["rr"] for c in responder),
        "erros_de_contrato": sum(1 for c in casos if c["resultado"].get("erro")),
        "tokens_entrada_medio": _media(c["resultado"]["tokens_entrada"] for c in casos),
        "latencia_media_s": _media(c["resultado"]["latencia_s"] for c in casos),
    }


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------

def aplicar_ragas(registros: list[dict], casos: list[dict]) -> None:
    from evals.ragas_eval import avaliar_ragas

    referencias = {c["id"]: c["referencia"] for c in casos}
    alvos = [r for r in registros if not r["deve_recusar"]]
    amostras = [{
        "user_input": r["pergunta"],
        "response": r["resultado"]["texto"],
        "retrieved_contexts": r["resultado"]["contextos"] or ["(sem contexto recuperado)"],
        "reference": referencias[r["id"]],
    } for r in alvos]
    for registro, nota in zip(alvos, avaliar_ragas(amostras)):
        registro["ragas"] = nota


def reavaliar_ragas(nome: str, com_ragas: bool = True) -> dict:
    """Recalcula só o RAGAS de um resultado já gerado, sem gerar de novo."""
    arquivo = DIRETORIO_RESULTADOS / f"{nome}.json"
    saida = json.loads(arquivo.read_text(encoding="utf-8"))
    casos = json.loads(ARQUIVO_EVAL.read_text(encoding="utf-8"))["casos"]
    por_id = {c["id"]: c for c in casos}
    for registro in saida["casos"]:
        caso = por_id[registro["id"]]
        registro["evidencia"] = acerto_evidencia(registro["resultado"]["contextos"], caso.get("evidencias", []))
        registro["violacoes"] = violacoes(registro["resultado"]["texto"], caso.get("proibidos", []))
    if com_ragas:
        aplicar_ragas(saida["casos"], casos)
    saida["agregado"] = agregar(saida["casos"])
    arquivo.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    return saida


def executar_eval(cfg: dict, nome: str, com_ragas: bool = True, workers: int = 2, ids: list[int] | None = None) -> dict:
    casos = json.loads(ARQUIVO_EVAL.read_text(encoding="utf-8"))["casos"]
    if ids:
        casos = [c for c in casos if c["id"] in ids]
    if cfg["arquitetura"] != "rag":
        # FAISS e torch disputam o runtime OpenMP quando chamados de várias
        # threads no macOS e derrubam o processo sem traceback. Os baselines
        # rodam em série.
        workers = 1
    fabrica = {"rag": _executor_rag, "sprint3": _executor_sprint3, "sprint2": _executor_sprint2}[cfg["arquitetura"]]
    executar, parametros = fabrica(cfg)

    inicio = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=workers)
    futuros = [pool.submit(executar, caso) for caso in casos]
    resultados = []
    for caso, futuro in zip(casos, futuros):
        try:
            resultados.append(futuro.result(timeout=TEMPO_MAXIMO_POR_CASO_S))
        except Exception as excecao:
            # Caso que não termina (o provedor mantém o stream aberto sem
            # concluir) vira resultado de erro, em vez de travar a medição.
            resultados.append(_resultado_de_falha(f"{type(excecao).__name__}: {str(excecao)[:200]}"))
    pool.shutdown(wait=False, cancel_futures=True)
    tempo_geracao = time.perf_counter() - inicio

    registros = []
    for caso, resultado in zip(casos, resultados):
        registros.append({
            **{k: caso[k] for k in ("id", "classe", "categoria", "pergunta", "deve_recusar", "fontes_esperadas")},
            "resultado": resultado,
            "manual": {
                "fidelidade": None if resultado["recusou"] else fidelidade_manual(resultado["texto"], resultado["contextos"], caso["pergunta"]),
                "relevancia": None if caso["deve_recusar"] else relevancia_manual(resultado["texto"], caso["criterios"]),
            },
            "violacoes": violacoes(resultado["texto"], caso.get("proibidos", [])),
            "recuperacao": (
                metricas_recuperacao(resultado["arquivos_recuperados"], caso["fontes_esperadas"])
                if cfg["arquitetura"] == "rag" else {"hit": None, "rr": None}
            ),
            "evidencia": acerto_evidencia(resultado["contextos"], caso.get("evidencias", [])),
        })

    if com_ragas:
        aplicar_ragas(registros, casos)

    saida = {
        "nome": nome, "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "configuracao": cfg, "parametros_modelo": parametros.como_dicionario(),
        "tempo_geracao_s": round(tempo_geracao, 1), "agregado": agregar(registros), "casos": registros,
    }
    DIRETORIO_RESULTADOS.mkdir(parents=True, exist_ok=True)
    (DIRETORIO_RESULTADOS / f"{nome}.json").write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    return saida


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--preset", choices=sorted(PRESETS))
    a.add_argument("--reavaliar-ragas", metavar="NOME", help="recalcula só o RAGAS de evals/resultados/NOME.json")
    a.add_argument("--nome")
    a.add_argument("--prompt"); a.add_argument("--chunk", type=int); a.add_argument("--overlap", type=int)
    a.add_argument("--k", type=int); a.add_argument("--limiar", type=float); a.add_argument("--modelo")
    a.add_argument("--temperature", type=float); a.add_argument("--top-p", type=float, dest="top_p")
    a.add_argument("--max-tokens", type=int, dest="max_tokens")
    a.add_argument("--hibrida", action=argparse.BooleanOptionalAction, default=None)
    a.add_argument("--expansao", action=argparse.BooleanOptionalAction, default=None)
    a.add_argument("--rerank", action=argparse.BooleanOptionalAction, default=None)
    a.add_argument("--prefixo", action=argparse.BooleanOptionalAction, default=None)
    a.add_argument("--sanitizar", action=argparse.BooleanOptionalAction, default=None)
    a.add_argument("--cabecalho", action=argparse.BooleanOptionalAction, default=None)
    a.add_argument("--guardrails", action=argparse.BooleanOptionalAction, default=None)
    a.add_argument("--sem-ragas", action="store_true")
    a.add_argument("--workers", type=int, default=2)
    a.add_argument("--ids", type=int, nargs="*")
    o = a.parse_args()

    if o.reavaliar_ragas:
        saida = reavaliar_ragas(o.reavaliar_ragas, com_ragas=not o.sem_ragas)
        print(json.dumps({"nome": o.reavaliar_ragas, **saida["agregado"]}, ensure_ascii=False, indent=1))
        return 0
    if not o.preset:
        a.error("informe --preset ou --reavaliar-ragas")

    cfg = {**PADROES, **PRESETS[o.preset]}
    for chave in ("prompt", "chunk", "overlap", "k", "limiar", "modelo", "temperature", "top_p",
                  "max_tokens", "hibrida", "expansao", "rerank", "prefixo", "sanitizar", "cabecalho", "guardrails"):
        valor = getattr(o, chave)
        if valor is not None:
            cfg[chave] = valor
    nome = o.nome or o.preset
    saida = executar_eval(cfg, nome, com_ragas=not o.sem_ragas, workers=o.workers, ids=o.ids)
    print(json.dumps({"nome": nome, "configuracao": cfg, **saida["agregado"]}, ensure_ascii=False, indent=1), flush=True)
    # Threads de casos abortados por tempo ainda podem estar presas no stream
    # do provedor; o resultado já está gravado, então o processo sai sem
    # esperar por elas.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
