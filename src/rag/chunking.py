"""
Estratégia de chunking (Aulas 06 e 07): `RecursiveCharacterTextSplitter`.

A escolha de tamanho e sobreposição foi medida, não arbitrada: ver
`evals/chunking_sweep.json` e `docs/relatorio_rag.md`. Os separadores seguem a
hierarquia natural dos documentos da base (parágrafo, linha, frase, palavra),
para que o corte caia preferencialmente em fronteira de sentido.

Cada fragmento herda os metadados da página e recebe a seção em que começa,
identificador estável e a marcação de suspeita de injeção, que alimenta a
defesa descrita em `src/guardrails/document_injection.py`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.guardrails.document_injection import sanitizar_trecho

SEPARADORES = ["\n\n", "\n", ". ", "; ", " ", ""]

# Artigos de norma citados no fragmento ("Art. 554."), usados na citação da
# fonte: em uma resolução de 300 páginas, "Seção III" não localiza o leitor,
# o número do artigo localiza.
PADRAO_ARTIGO = re.compile(r"\bArt\.\s*(\d{1,3})")

# Fragmentos menores do que isso são, na prática, rodapé, número de página ou
# cabeçalho repetido: não carregam conteúdo recuperável.
TAMANHO_MINIMO_UTIL = 60


@dataclass(frozen=True)
class EstrategiaChunking:
    tamanho: int = 500
    sobreposicao: int = 50

    @property
    def rotulo(self) -> str:
        return f"{self.tamanho}/{self.sobreposicao}"


ESTRATEGIA_PADRAO = EstrategiaChunking()


def _e_sumario(texto: str) -> bool:
    """Fragmento de sumário: muitas entradas "título … página" e pouca prosa.

    Sumários de especificações longas (OCPP, MODBUS, REN 1.000) casam com
    qualquer pergunta por conterem todos os títulos do documento, e ocupavam
    posições do top-k sem trazer conteúdo.
    """
    return texto.count("…") >= 4 and texto.count("…") * 60 > len(texto) * 0.5


def _secao_do_fragmento(metadados: dict, inicio: int) -> str:
    """Último cabeçalho da página que começa antes do fragmento."""
    secao = metadados.get("secao_inicial", "")
    for posicao, titulo in json.loads(metadados.get("cabecalhos", "[]")):
        if posicao <= inicio:
            secao = titulo
        else:
            break
    return secao


def _identificador(metadados: dict, inicio: int, estrategia: EstrategiaChunking) -> str:
    chave = f"{metadados['arquivo']}|{metadados['pagina']}|{inicio}|{estrategia.rotulo}"
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()[:16]


def cabecalho_contextual(metadados: dict) -> str:
    """Linha de contexto prefixada ao fragmento: documento, seção e artigos.

    Medido no benchmark de recuperação: com chunk de 500 caracteres, o corte
    separa o título da seção do conteúdo ("5. Formas de pagamento" fica num
    fragmento, "Pré-autorização: R$ 80,00" no seguinte), e o fragmento com o
    dado deixa de ser encontrável pela pergunta. O cabeçalho devolve a cada
    fragmento o contexto do documento, tanto para o embedding e o BM25 quanto
    para o LLM que lê o trecho.
    """
    partes = [metadados.get("titulo", "")]
    if metadados.get("secao"):
        partes.append(metadados["secao"])
    if metadados.get("artigos"):
        partes.append("Art. " + metadados["artigos"])
    return "[" + " · ".join(p for p in partes if p) + "]"


def dividir(
    paginas: list[Document],
    estrategia: EstrategiaChunking = ESTRATEGIA_PADRAO,
    sanitizar: bool = True,
    com_cabecalho: bool = True,
) -> list[Document]:
    """Divide as páginas em fragmentos indexáveis."""
    divisor = RecursiveCharacterTextSplitter(
        chunk_size=estrategia.tamanho,
        chunk_overlap=estrategia.sobreposicao,
        separators=SEPARADORES,
        add_start_index=True,
    )
    fragmentos = []
    for fragmento in divisor.split_documents(paginas):
        texto = fragmento.page_content.strip()
        if len(texto) < TAMANHO_MINIMO_UTIL or _e_sumario(texto):
            continue
        metadados = dict(fragmento.metadata)
        inicio = int(metadados.pop("start_index", 0))
        metadados["secao"] = _secao_do_fragmento(metadados, inicio)
        metadados["chunk_id"] = _identificador(metadados, inicio, estrategia)
        metadados["estrategia"] = estrategia.rotulo
        artigos = list(dict.fromkeys(PADRAO_ARTIGO.findall(texto)))
        metadados["artigos"] = ", ".join(artigos[:6])
        metadados.pop("cabecalhos", None)
        metadados.pop("secao_inicial", None)

        suspeito, motivos = False, []
        if sanitizar:
            texto, suspeito, motivos = sanitizar_trecho(texto)
        metadados["suspeito_injecao"] = suspeito
        metadados["motivos_injecao"] = "; ".join(motivos)
        if com_cabecalho:
            texto = f"{cabecalho_contextual(metadados)}\n{texto}"

        fragmentos.append(Document(page_content=texto, metadata=metadados))
    return fragmentos
