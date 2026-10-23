"""
Proteção contra prompt injection via documentos (Sprint 4, item 6 do escopo).

Na Sprint 3 a injeção só podia chegar pela pergunta do operador, e era barrada
por `moderation.py`. Com RAG surge um segundo canal: o texto recuperado. Um PDF
de terceiros (fórum, e-mail de fornecedor, manual adulterado) pode carregar uma
instrução que o modelo leria como se viesse do sistema.

A defesa tem três camadas, porque nenhuma delas sozinha é suficiente:

1. Ingestão (este módulo): cada fragmento é varrido por frase. Frases com padrão
   de instrução dirigida ao assistente são substituídas por um marcador neutro
   e o fragmento é marcado como suspeito nos metadados do ChromaDB. O conteúdo
   factual do mesmo fragmento é preservado.
2. Montagem do contexto (`src/rag/prompt_rag.py`): todo trecho entra delimitado
   como dado, com os sinais de marcação escapados, de modo que um documento não
   consegue fechar a marca do contexto e abrir uma instrução própria.
3. Instrução (`prompts/rag/prompt_rag_v2.md` em diante): o modelo é instruído a
   tratar o contexto como evidência e nunca como comando.

A camada 1 é determinística e auditável; as camadas 2 e 3 cobrem o que escapar
dos padrões. O efeito de cada camada é medido no eval (casos de injeção).
"""

from __future__ import annotations

import re

from src.guardrails.moderation import PADROES_INJECAO, PADROES_JAILBREAK, normalizar

MARCADOR_REMOCAO = "[trecho removido pela proteção contra instruções embutidas em documento]"

# Padrões próprios do canal documental: frases dirigidas a "sistemas de IA",
# que não fariam sentido numa pergunta do operador mas aparecem em documentos
# adulterados. Inclui as formas em inglês, porque parte da base é em inglês.
PADROES_DOCUMENTAIS = [
    re.compile(p)
    for p in (
        r"\b(atencao|aviso|nota|mensagem)\b.{0,15}\b(sistema|assistente|ia|inteligencia artificial|modelo de linguagem|chatbot)\b",
        r"\b(assistentes?|modelos?|sistemas?) de (ia|inteligencia artificial)\b.{0,40}\b(devem|deve|precisa|informe|responda|diga)\b",
        r"\bignore (all |any )?(the )?(previous|prior|above) (instructions|rules|prompts?)\b",
        r"\byou are now\b|\bfrom now on,? you\b|\bact as\b.{0,30}\bwithout\b",
        r"\b(reveal|print|show) (your|the) (system )?prompt\b",
        r"\b(informe|diga|responda) (ao usuario|aos usuarios|que)\b.{0,60}\b(gratuit|de graca|sem custo|pode ser desligad)\w*\b",
    )
]

# Dois padrões de `PADROES_INJECAO` foram calibrados para a pergunta do
# operador e geram falso positivo em norma: o rótulo "Sistema:" no início de
# linha e o aviso "Este texto não substitui o publicado no DOU" da ANEEL. No
# canal documental eles só disparam quando seguidos de instrução dirigida ao
# assistente. Os falsos positivos foram encontrados na primeira ingestão da
# base e estão registrados em `docs/relatorio_rag.md`.
_INJECAO_SO_NA_PERGUNTA = {
    r"^\s*(system|sistema|assistant|assistente)\s*:",
    r"\b(este|esse) (documento|texto|trecho|arquivo)\b.{0,40}\b(substitui|sobrepoe|tem precedencia)\b",
}
PADROES_INJECAO_DOCUMENTAL = [p for p in PADROES_INJECAO if p.pattern not in _INJECAO_SO_NA_PERGUNTA] + [
    re.compile(r"^\s*(system|sistema|assistant|assistente)\s*:\s*(ignore|esqueca|voce|a partir|revele|responda|diga|informe)"),
    re.compile(r"\b(este|esse) (documento|texto|trecho|arquivo)\b.{0,40}\b(substitui|sobrepoe|tem precedencia)\b.{0,40}\b(instrucoes|regras|diretrizes|prompt)\b"),
]

TODOS_OS_PADROES = list(PADROES_JAILBREAK) + PADROES_INJECAO_DOCUMENTAL + PADROES_DOCUMENTAIS

# Fronteira de frase: ponto, exclamação, interrogação ou dois-pontos seguidos de
# espaço, ou quebra de linha. Dois-pontos entram porque instruções embutidas
# costumam vir no formato "ATENÇÃO SISTEMA: faça X".
_FRONTEIRA = re.compile(r"(?<=[.!?:])\s+|\n+")


def detectar_injecao(texto: str) -> list[str]:
    """Devolve os trechos normalizados que casaram com algum padrão."""
    normalizado = normalizar(texto)
    gatilhos = []
    for padrao in TODOS_OS_PADROES:
        ocorrencia = padrao.search(normalizado)
        if ocorrencia:
            gatilhos.append(ocorrencia.group(0))
    return gatilhos


def sanitizar_trecho(texto: str) -> tuple[str, bool, list[str]]:
    """Remove as frases com instrução embutida e preserva o restante.

    Retorna o texto sanitizado, se houve remoção e os gatilhos encontrados.
    Frases removidas em sequência colapsam em um único marcador.
    """
    frases = [f for f in _FRONTEIRA.split(texto) if f and f.strip()]
    mantidas: list[str] = []
    gatilhos: list[str] = []
    for frase in frases:
        encontrados = detectar_injecao(frase)
        if encontrados:
            gatilhos.extend(encontrados)
            if not mantidas or mantidas[-1] != MARCADOR_REMOCAO:
                mantidas.append(MARCADOR_REMOCAO)
        else:
            mantidas.append(frase.strip())
    if not gatilhos:
        return texto, False, []
    return " ".join(mantidas), True, gatilhos
