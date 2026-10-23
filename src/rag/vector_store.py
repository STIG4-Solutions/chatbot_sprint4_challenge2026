"""
Vector store persistente (Aula 05): ChromaDB.

Na Sprint 3 o índice FAISS era reconstruído em memória a cada execução, a partir
de seis parágrafos fixos. Com a base em PDF isso deixa de ser aceitável: a
vetorização da base inteira custa minutos, e um índice que morre com o processo
não pode ser auditado nem compartilhado pela interface e pelo eval.

O ChromaDB persiste em disco (`.chroma/`, fora do Git). Cada configuração de
indexação (estratégia de chunking, modelo de embeddings, uso de prefixo,
sanitização) gera uma coleção própria, identificada por uma impressão digital.
Assim o eval compara configurações sem que uma sobrescreva a outra, e a
reindexação só acontece quando um PDF ou um parâmetro muda de fato.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.config import DIRETORIO_BASE_CONHECIMENTO, Configuracao, carregar_configuracao
from src.rag.chunking import ESTRATEGIA_PADRAO, EstrategiaChunking, dividir
from src.rag.embeddings import criar_embeddings
from src.rag.loader import carregar_base

TAMANHO_LOTE = 64


@dataclass(frozen=True)
class ConfiguracaoIndice:
    estrategia: EstrategiaChunking = ESTRATEGIA_PADRAO
    com_prefixo: bool = True
    sanitizar: bool = True
    cabecalho: bool = True

    def impressao_digital(self, modelo_embeddings: str, diretorio: Path) -> str:
        """Hash dos PDFs e dos parâmetros que determinam o conteúdo do índice."""
        h = hashlib.sha256()
        for pdf in sorted(Path(diretorio).glob("*.pdf")):
            h.update(pdf.name.encode())
            h.update(hashlib.sha256(pdf.read_bytes()).digest())
        h.update((Path(diretorio) / "manifesto.json").read_bytes())
        assinatura = f"{self.estrategia.rotulo}|{modelo_embeddings}|{self.com_prefixo}|{self.sanitizar}"
        # Sem cabeçalho a assinatura é a mesma das coleções criadas antes da
        # opção existir, para que as iterações 1 a 3 continuem reproduzíveis.
        if self.cabecalho:
            assinatura += "|cabecalho"
        h.update(assinatura.encode())
        return h.hexdigest()[:12]

    def nome_colecao(self, modelo_embeddings: str, diretorio: Path) -> str:
        return f"chargegrid_{self.impressao_digital(modelo_embeddings, diretorio)}"


def _cliente(configuracao: Configuracao) -> chromadb.ClientAPI:
    Path(configuracao.diretorio_chroma).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=configuracao.diretorio_chroma)


def abrir_indice(
    configuracao_indice: ConfiguracaoIndice = ConfiguracaoIndice(),
    configuracao: Configuracao | None = None,
    diretorio: Path = DIRETORIO_BASE_CONHECIMENTO,
    reindexar: bool = False,
    verbose: bool = False,
) -> Chroma:
    """Abre a coleção persistente da configuração, indexando se necessário."""
    configuracao = configuracao or carregar_configuracao()
    cliente = _cliente(configuracao)
    nome = configuracao_indice.nome_colecao(configuracao.modelo_embeddings, diretorio)
    embeddings = criar_embeddings(configuracao, com_prefixo=configuracao_indice.com_prefixo)

    existentes = {c.name for c in cliente.list_collections()}
    if reindexar and nome in existentes:
        cliente.delete_collection(nome)
        existentes.discard(nome)

    loja = Chroma(
        client=cliente,
        collection_name=nome,
        embedding_function=embeddings,
        collection_metadata={
            "hnsw:space": "cosine",
            "estrategia": configuracao_indice.estrategia.rotulo,
            "modelo_embeddings": configuracao.modelo_embeddings,
            "com_prefixo": configuracao_indice.com_prefixo,
            "sanitizar": configuracao_indice.sanitizar,
            "cabecalho": configuracao_indice.cabecalho,
        },
    )

    if nome not in existentes or loja._collection.count() == 0:
        fragmentos = dividir(
            carregar_base(diretorio),
            configuracao_indice.estrategia,
            sanitizar=configuracao_indice.sanitizar,
            com_cabecalho=configuracao_indice.cabecalho,
        )
        _indexar(loja, fragmentos, verbose)
    return loja


def _indexar(loja: Chroma, fragmentos: list[Document], verbose: bool) -> None:
    for inicio in range(0, len(fragmentos), TAMANHO_LOTE):
        lote = fragmentos[inicio : inicio + TAMANHO_LOTE]
        loja.add_documents(lote, ids=[f.metadata["chunk_id"] for f in lote])
        if verbose:
            print(f"  indexados {min(inicio + TAMANHO_LOTE, len(fragmentos))}/{len(fragmentos)}")


def todos_os_fragmentos(loja: Chroma) -> list[Document]:
    """Lê a coleção inteira, usado pela busca lexical (BM25) do retriever híbrido."""
    dados = loja.get(include=["documents", "metadatas"])
    return [
        Document(page_content=texto, metadata=meta or {})
        for texto, meta in zip(dados["documents"], dados["metadatas"])
    ]
