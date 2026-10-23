"""
Embeddings (Aula 05): `nomic-embed-text` servido pelo Ollama.

O `nomic-embed-text` foi treinado com prefixos de tarefa: o texto indexado deve
entrar como "search_document: ..." e a consulta como "search_query: ...". Sem o
prefixo o modelo continua funcionando, mas consulta e documento passam a ser
projetados como se fossem do mesmo tipo, o que reduz a separação entre trechos
relevantes e irrelevantes. O efeito foi medido (ver `docs/relatorio_rag.md`).
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

from src.config import Configuracao, carregar_configuracao

PREFIXO_DOCUMENTO = "search_document: "
PREFIXO_CONSULTA = "search_query: "


class NomicEmbeddings(Embeddings):
    """Adaptador que aplica os prefixos de tarefa do `nomic-embed-text`."""

    def __init__(self, base: OllamaEmbeddings, com_prefixo: bool = True) -> None:
        self.base = base
        self.com_prefixo = com_prefixo

    def embed_documents(self, textos: list[str]) -> list[list[float]]:
        if self.com_prefixo:
            textos = [PREFIXO_DOCUMENTO + t for t in textos]
        return self.base.embed_documents(textos)

    def embed_query(self, texto: str) -> list[float]:
        if self.com_prefixo:
            texto = PREFIXO_CONSULTA + texto
        return self.base.embed_query(texto)


def criar_embeddings(
    configuracao: Configuracao | None = None,
    com_prefixo: bool = True,
) -> NomicEmbeddings:
    configuracao = configuracao or carregar_configuracao()
    base = OllamaEmbeddings(
        model=configuracao.modelo_embeddings,
        base_url=configuracao.embeddings_base_url,
    )
    return NomicEmbeddings(base, com_prefixo=com_prefixo)
