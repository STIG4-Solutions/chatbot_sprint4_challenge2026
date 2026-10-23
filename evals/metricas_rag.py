"""
Métricas do eval RAG: rubrica manual de fallback, recusa, citação e recuperação.

A métrica principal é o RAGAS (`evals/ragas_eval.py`). Este módulo implementa a
rubrica manual equivalente exigida como fallback (§8 do escopo), documentada em
`evals/RUBRICA_FALLBACK.md`, e as métricas que o RAGAS não cobre: acerto de
recusa, presença e validade de citação, violação de conteúdo proibido e
qualidade da recuperação (hit@k e MRR sobre as fontes esperadas).

A rubrica é determinística de propósito: aplicada ao mesmo eval set em cada
iteração, ela não varia com o juiz, e serve de verificação cruzada do RAGAS.
"""

from __future__ import annotations

import re

from src.guardrails.moderation import normalizar

PALAVRAS_VAZIAS = set(
    "a o as os um uma uns umas de do da dos das no na nos nas em por para com sem sob "
    "que se ou e mas como mais menos muito pouco ja nao sim sua seu suas seus ele ela "
    "eles elas isso esse essa este esta esses essas estes estas entre sobre ate quando "
    "onde qual quais cada todo toda todos todas pelo pela pelos pelas deve devem pode "
    "podem ser sao foi esta estao ter tem tambem apenas ainda assim entao porque the of "
    "and to in is for on with by".split()
)

PADRAO_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")
PADRAO_FRASE = re.compile(r"(?<=[.!?])\s+")
PADRAO_MARCADOR = re.compile(r"\s*\[\d{1,2}\]")

SINAIS_DE_RECUSA = (
    "nao esta na base", "nao consta", "nao ha informacao", "nao contem", "nao encontr",
    "fora do escopo", "fora de escopo", "nao atendo", "nao posso", "nao oriento",
    "nao emito", "nao recomendo", "recuso", "nao e possivel responder", "nao foi possivel",
    "nao ha dados", "nao disponho", "sem informacao", "nao estao na base",
)


def _numeros(texto: str) -> set[str]:
    return {n.replace(",", ".").rstrip(".") for n in PADRAO_NUMERO.findall(texto)}


def _palavras_de_conteudo(texto_normalizado: str) -> list[str]:
    return [
        p for p in re.findall(r"[a-z0-9]+", texto_normalizado)
        if len(p) >= 5 and p not in PALAVRAS_VAZIAS
    ]


def fidelidade_manual(
    resposta: str, contextos: list[str], pergunta: str = "", cobertura_minima: float = 0.6
) -> float | None:
    """Fração das frases da resposta sustentadas pelo contexto recuperado.

    Uma frase é sustentada quando (a) todo número que ela afirma aparece no
    contexto e (b) ao menos 60% das suas palavras de conteúdo aparecem no
    contexto ou na pergunta (o operador pode informar o próprio consumo) e
    (b) ao menos 60% das suas palavras de conteúdo aparecem no contexto. Número
    derivado por cálculo não conta como sustentado: a rubrica é conservadora.
    É a contraparte lexical do faithfulness do RAGAS, que extrai
    afirmações com um LLM e verifica cada uma contra o contexto.
    """
    texto = PADRAO_MARCADOR.sub("", resposta or "").strip()
    if not texto or not contextos:
        return None
    contexto = normalizar(" ".join(contextos))
    numeros_contexto = _numeros(contexto) | _numeros(normalizar(pergunta))
    palavras_contexto = set(_palavras_de_conteudo(contexto))
    frases = [f for f in PADRAO_FRASE.split(texto) if len(f.strip()) > 15]
    if not frases:
        return None
    sustentadas = 0
    for frase in frases:
        normal = normalizar(frase)
        if _numeros(normal) - numeros_contexto:
            continue
        palavras = _palavras_de_conteudo(normal)
        if not palavras or sum(p in palavras_contexto for p in palavras) / len(palavras) >= cobertura_minima:
            sustentadas += 1
    return sustentadas / len(frases)


def relevancia_manual(resposta: str, criterios: list[list[str]]) -> float | None:
    """Fração dos elementos-chave da resposta de referência que a resposta cobre.

    Cada critério é um grupo de formas equivalentes; o critério conta quando
    qualquer forma aparece. É a contraparte do answer_relevancy: mede se a
    resposta trata do que foi perguntado, tomando a referência como gabarito.
    """
    if not criterios:
        return None
    texto = normalizar(resposta or "")
    return sum(any(normalizar(f) in texto for f in grupo) for grupo in criterios) / len(criterios)


def parece_recusa(texto: str) -> bool:
    normal = normalizar(texto or "")
    return any(sinal in normal for sinal in SINAIS_DE_RECUSA)


def violacoes(texto: str, proibidos: list[str]) -> list[str]:
    normal = normalizar(texto or "")
    return [p for p in proibidos if normalizar(p) in normal]


def metricas_recuperacao(arquivos_recuperados: list[str], fontes_esperadas: list[str]) -> dict:
    """hit@k e reciprocal rank da primeira fonte esperada entre as recuperadas."""
    if not fontes_esperadas:
        return {"hit": None, "rr": None}
    for posicao, arquivo in enumerate(arquivos_recuperados, start=1):
        if arquivo in fontes_esperadas:
            return {"hit": 1.0, "rr": 1.0 / posicao}
    return {"hit": 0.0, "rr": 0.0}


def acerto_evidencia(contextos: list[str], evidencias: list[str]) -> dict:
    """Se algum trecho recuperado contém a evidência que responde à pergunta.

    `hit` indica presença em qualquer posição; `rr` é o recíproco da posição do
    primeiro trecho com evidência. Funciona para qualquer arquitetura, porque
    olha o texto recuperado e não o nome do arquivo, o que permite comparar a
    recuperação da Sprint 4 com a das Sprints 1 a 3 no mesmo critério.
    """
    if not evidencias:
        return {"hit": None, "rr": None}
    alvos = [normalizar(e) for e in evidencias]
    for posicao, contexto in enumerate(contextos, start=1):
        texto = normalizar(contexto)
        if any(a in texto for a in alvos):
            return {"hit": 1.0, "rr": 1.0 / posicao}
    return {"hit": 0.0, "rr": 0.0}
