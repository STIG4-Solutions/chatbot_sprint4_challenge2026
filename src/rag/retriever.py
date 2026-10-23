"""
Recuperação (Aulas 06 e 07): busca vetorial, busca híbrida e limiar de relevância.

Três decisões, todas medidas no eval:

1. Escore de relevância explícito. A busca devolve a similaridade de cosseno de
   cada trecho. Quando o melhor trecho fica abaixo do limiar, a base não tem
   resposta para a pergunta e o pipeline recusa sem chamar o modelo, em vez de
   entregar ao LLM um contexto irrelevante que ele tentaria aproveitar.
2. Busca híbrida. Perguntas do operador citam códigos e termos exatos
   ("SetChargingProfile", "Art. 4º", "DC Fast") que o embedding aproxima mal. A
   busca lexical BM25 é fundida à vetorial por Reciprocal Rank Fusion (RRF).
3. Expansão de consulta e reranking (opcionais, `src/rag/reranking.py`).
   A pergunta ganha reformulações em português e em inglês técnico, e os
   candidatos fundidos são reordenados por um LLM auxiliar.
4. Diversidade de fonte. No máximo `max_por_documento` trechos do mesmo PDF,
   para que um documento longo não ocupe todo o contexto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from langchain_chroma import Chroma
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from src.rag.vector_store import ConfiguracaoIndice, abrir_indice, todos_os_fragmentos

CONSTANTE_RRF = 60


@dataclass(frozen=True)
class ParametrosRecuperacao:
    k: int = 6
    limiar_relevancia: float = 0.0
    hibrida: bool = True
    candidatos: int = 20
    max_por_documento: int = 3
    expansao: bool = True
    rerank: bool = True
    candidatos_rerank: int = 12
    nota_minima_rerank: int = 1


@dataclass
class TrechoRecuperado:
    documento: Document
    relevancia: float
    posicao: int
    origem_busca: str = "vetorial"

    @property
    def metadados(self) -> dict:
        return self.documento.metadata

    def rotulo_citacao(self) -> str:
        m = self.metadados
        partes = [m.get("titulo", m.get("fonte")), f"p. {m.get('pagina')}"]
        if m.get("artigos"):
            prefixo = "Art." if "," not in m["artigos"] else "Arts."
            partes.append(f"{prefixo} {m['artigos']}")
        elif m.get("secao"):
            partes.append(_rotulo_secao(m["secao"]))
        return ", ".join(partes)

    def como_dicionario(self) -> dict:
        m = self.metadados
        return {
            "posicao": self.posicao,
            "documento": m.get("titulo"),
            "arquivo": m.get("arquivo"),
            "pagina": m.get("pagina"),
            "secao": m.get("secao"),
            "artigos": m.get("artigos"),
            "tipo_fonte": m.get("tipo_fonte"),
            "relevancia": round(self.relevancia, 4),
            "suspeito_injecao": bool(m.get("suspeito_injecao")),
            "chunk_id": m.get("chunk_id"),
            "texto": self.documento.page_content,
        }


@dataclass
class ResultadoRecuperacao:
    trechos: list[TrechoRecuperado]
    melhor_relevancia: float
    suficiente: bool
    parametros: ParametrosRecuperacao = field(default_factory=ParametrosRecuperacao)


def _rotulo_secao(secao: str) -> str:
    """"Seção VII" e "3.2 Limiares" já se identificam; título solto ganha o prefixo."""
    if not secao:
        return ""
    if re.match(r"(?i)(se[çc][ãa]o|cap[íi]tulo|art\.|\d)", secao):
        return secao
    return f"seção {secao}"


def _tokenizar(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", texto)


class Recuperador:
    """Retriever sobre a coleção persistente do ChromaDB."""

    def __init__(
        self,
        parametros: ParametrosRecuperacao = ParametrosRecuperacao(),
        configuracao_indice: ConfiguracaoIndice = ConfiguracaoIndice(),
        loja: Chroma | None = None,
        auxiliar=None,
    ) -> None:
        self.parametros = parametros
        self.auxiliar = auxiliar
        if (parametros.expansao or parametros.rerank) and auxiliar is None:
            from src.rag.reranking import AuxiliarLLM

            self.auxiliar = AuxiliarLLM()
        self.loja = loja or abrir_indice(configuracao_indice)
        self._bm25: BM25Okapi | None = None
        self._corpus: list[Document] = []

    # -- busca lexical -------------------------------------------------------

    def _indice_lexical(self) -> BM25Okapi:
        if self._bm25 is None:
            self._corpus = todos_os_fragmentos(self.loja)
            self._bm25 = BM25Okapi([_tokenizar(d.page_content) for d in self._corpus])
        return self._bm25

    def _busca_lexical(self, pergunta: str, n: int) -> list[Document]:
        escores = self._indice_lexical().get_scores(_tokenizar(pergunta))
        ordem = sorted(range(len(escores)), key=lambda i: escores[i], reverse=True)[:n]
        return [self._corpus[i] for i in ordem if escores[i] > 0]

    # -- busca ---------------------------------------------------------------

    def buscar(self, pergunta: str) -> ResultadoRecuperacao:
        p = self.parametros
        if not pergunta or not pergunta.strip():
            return ResultadoRecuperacao([], 0.0, False, p)

        consultas = [pergunta]
        if p.expansao:
            consultas += self.auxiliar.expandir(pergunta)

        relevancia: dict[str, float] = {}
        listas: list[list[Document]] = []
        for consulta in consultas:
            vetoriais = self.loja.similarity_search_with_relevance_scores(consulta, k=p.candidatos)
            listas.append([d for d, _ in vetoriais])
            if consulta is pergunta:
                # O limiar e a relevância exibida usam sempre a pergunta original.
                relevancia.update({d.metadata["chunk_id"]: r for d, r in vetoriais})
            if p.hibrida:
                listas.append(self._busca_lexical(consulta, p.candidatos))
        melhor = max(relevancia.values(), default=0.0)

        if len(listas) > 1:
            fusao: dict[str, float] = {}
            por_id: dict[str, Document] = {}
            for lista in listas:
                for posicao, documento in enumerate(lista):
                    cid = documento.metadata["chunk_id"]
                    fusao[cid] = fusao.get(cid, 0.0) + 1.0 / (CONSTANTE_RRF + posicao + 1)
                    por_id[cid] = documento
            ordenados = [por_id[c] for c in sorted(fusao, key=fusao.get, reverse=True)]
        else:
            ordenados = listas[0]

        if p.rerank and ordenados:
            reranqueados = self.auxiliar.reranquear(pergunta, ordenados[: p.candidatos_rerank])
            uteis = [d for d, nota in reranqueados if nota >= p.nota_minima_rerank]
            ordenados = uteis or [d for d, _ in reranqueados]

        candidatos = [(d, relevancia.get(d.metadata["chunk_id"])) for d in ordenados]

        trechos: list[TrechoRecuperado] = []
        por_documento: dict[str, int] = {}
        for documento, rel in candidatos:
            arquivo = documento.metadata.get("arquivo", "")
            if por_documento.get(arquivo, 0) >= p.max_por_documento:
                continue
            if rel is None:
                # Trecho trazido só pela busca lexical: mede a relevância
                # semântica para que o limiar e a interface tenham o mesmo
                # critério para todos os trechos.
                rel = self._relevancia_semantica(pergunta, documento)
                origem = "lexical"
            else:
                origem = "vetorial" if len(consultas) == 1 and not p.hibrida else "fusao"
            por_documento[arquivo] = por_documento.get(arquivo, 0) + 1
            trechos.append(TrechoRecuperado(documento, float(rel), len(trechos) + 1, origem))
            if len(trechos) >= p.k:
                break

        suficiente = bool(trechos) and melhor >= p.limiar_relevancia
        return ResultadoRecuperacao(trechos, float(melhor), suficiente, p)

    def _relevancia_semantica(self, pergunta: str, documento: Document) -> float:
        embeddings = self.loja.embeddings
        q = embeddings.embed_query(pergunta)
        d = embeddings.embed_documents([documento.page_content])[0]
        produto = sum(a * b for a, b in zip(q, d))
        norma = (sum(a * a for a in q) ** 0.5) * (sum(b * b for b in d) ** 0.5)
        return produto / norma if norma else 0.0
