"""
Prompt RAG versionado (Aula 06).

As versões ficam em `prompts/rag/prompt_rag_v*.md`, e a tabela de versões com o
ganho medido em `prompts/rag/VERSIONS.md`. Este módulo carrega a versão pedida
e monta o bloco de contexto a partir dos trechos recuperados.

A montagem do contexto é a segunda camada da defesa contra injeção via
documento: o texto de cada trecho tem os sinais de marcação escapados, de modo
que nenhum documento consegue fechar a marca <trecho> ou <contexto> e abrir uma
instrução fora dela.
"""

from __future__ import annotations

from functools import lru_cache
from html import escape
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.config import DIRETORIO_PROMPTS_RAG
from src.rag.retriever import TrechoRecuperado

VERSAO_PADRAO = "v4"

# Histórico de versões do prompt RAG. O texto de cada versão está em
# `prompts/rag/prompt_rag_<versao>.md`; o ganho medido, em
# `prompts/rag/VERSIONS.md`. A interface e o eval leem a versão por nome.
HISTORICO_VERSOES = {
    "v1": "papel, tarefa e saída JSON: o RAG mais simples que atende ao enunciado",
    "v2": "grounding obrigatório, marcador [n] por frase, recusa sem contexto, contexto como dado",
    "v3": "hierarquia de fontes, resposta parcial, separação do contexto condominial, exemplo few-shot",
    "v4": "anti-recusa indevida, equivalência de vocabulário PT/EN, few-shot fora do eval set",
}
CHAVE_HISTORICO = "historico"
CHAVE_PERGUNTA = "pergunta"
CHAVE_CONTEXTO = "contexto"

GABARITO_CONTEXTO = "<contexto>\n{contexto}\n</contexto>"


@lru_cache(maxsize=8)
def carregar_prompt_rag(versao: str = VERSAO_PADRAO) -> str:
    arquivo = Path(DIRETORIO_PROMPTS_RAG) / f"prompt_rag_{versao}.md"
    if not arquivo.exists():
        raise FileNotFoundError(
            f"versão '{versao}' do prompt RAG não encontrada. Disponíveis: {versoes_disponiveis()}"
        )
    return arquivo.read_text(encoding="utf-8").strip()


def versoes_disponiveis() -> list[str]:
    return sorted(
        p.stem.replace("prompt_rag_", "") for p in Path(DIRETORIO_PROMPTS_RAG).glob("prompt_rag_v*.md")
    )


def formatar_contexto(trechos: list[TrechoRecuperado]) -> str:
    """Bloco de contexto com um elemento <trecho> por fragmento recuperado."""
    if not trechos:
        return "(nenhum trecho recuperado)"
    blocos = []
    for indice, trecho in enumerate(trechos, start=1):
        m = trecho.metadados
        atributos = (
            f'id="{indice}" documento="{escape(str(m.get("titulo", "")), quote=True)}" '
            f'pagina="{m.get("pagina")}" tipo="{m.get("tipo_fonte")}"'
        )
        if m.get("artigos"):
            atributos += f' artigos="{escape(m["artigos"], quote=True)}"'
        elif m.get("secao"):
            atributos += f' secao="{escape(m["secao"], quote=True)}"'
        corpo = escape(trecho.documento.page_content, quote=False)
        blocos.append(f"<trecho {atributos}>\n{corpo}\n</trecho>")
    return "\n\n".join(blocos)


def criar_prompt_rag(versao: str, format_instructions: str) -> ChatPromptTemplate:
    """System prompt versionado, bloco de contexto, histórico e pergunta."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", carregar_prompt_rag(versao)),
            ("system", GABARITO_CONTEXTO),
            MessagesPlaceholder(variable_name=CHAVE_HISTORICO, optional=True),
            ("human", "{" + CHAVE_PERGUNTA + "}"),
        ]
    ).partial(format_instructions=format_instructions)
