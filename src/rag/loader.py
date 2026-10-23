"""
Carga da base de conhecimento em PDF (Aula 06): `PyMuPDFLoader`.

Nas Sprints 1 a 3 a base eram seis parágrafos escritos dentro do código
(`legacy/chatbot_sprint2.py`). Não havia documento de origem, página ou seção a
citar, e a resposta só podia apontar um rótulo genérico como "OCPP_spec".

Aqui a base passa a ser um diretório de PDFs (`data/knowledge_base/`), descritos
por um manifesto versionado. Cada página carregada recebe os metadados que a
citação exige (documento, página, seção) e os que a segurança exige (tipo de
fonte: oficial, do projeto ou não verificada).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_core.documents import Document

from src.config import DIRETORIO_BASE_CONHECIMENTO

ARQUIVO_MANIFESTO = "manifesto.json"

# Tipos de fonte, em ordem decrescente de confiança. O prompt RAG instrui o
# modelo a preferir a fonte mais confiável quando duas fontes divergem.
TIPOS_DE_FONTE = ("oficial", "projeto", "nao_verificada")


@dataclass(frozen=True)
class EntradaManifesto:
    arquivo: str
    titulo: str
    tipo: str
    origem: str
    descricao: str = ""


def ler_manifesto(diretorio: Path = DIRETORIO_BASE_CONHECIMENTO) -> dict[str, EntradaManifesto]:
    """Lê `manifesto.json`, que descreve título, tipo e origem de cada PDF.

    Todo PDF do diretório precisa estar no manifesto: arquivo sem procedência
    declarada não entra na base.
    """
    caminho = Path(diretorio) / ARQUIVO_MANIFESTO
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    entradas = {}
    for item in dados["documentos"]:
        entrada = EntradaManifesto(**item)
        if entrada.tipo not in TIPOS_DE_FONTE:
            raise ValueError(f"tipo de fonte inválido em {entrada.arquivo}: {entrada.tipo}")
        entradas[entrada.arquivo] = entrada
    return entradas


# ---------------------------------------------------------------------------
# Limpeza de texto extraído de PDF
# ---------------------------------------------------------------------------

def limpar_texto(texto: str) -> str:
    """Corrige os artefatos mais comuns da extração de PDF.

    - hifenização de fim de linha ("distri-\\nbuidora" vira "distribuidora")
    - espaços repetidos e linhas em branco em excesso
    - caracteres de controle que poluem o embedding
    """
    texto = texto.replace("\u00ad", "")
    # Linhas pontilhadas de sumário (". . . . . . 53") viram um único separador.
    texto = re.sub(r"(?:[ \t\u00a0]*\.){4,}[ \t\u00a0]*", " … ", texto)
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


# ---------------------------------------------------------------------------
# Seções
# ---------------------------------------------------------------------------

# Cabeçalhos reconhecidos no corpo da página quando o PDF não traz sumário
# (bookmarks): artigos e capítulos de norma, e títulos numerados de manual.
PADRAO_CABECALHO = re.compile(
    r"^(?:"
    r"(?:Art\.|Artigo)\s*\d+[ºo°]?.{0,60}"
    r"|CAP[ÍI]TULO\s+[IVXLC]+.{0,60}"
    r"|Se[çc][ãa]o\s+[IVXLC]+.{0,60}"
    r"|\d{1,2}(?:\.\d{1,2}){0,2}\.?\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n]{2,70}"
    r")$",
    re.MULTILINE,
)


def sumario_por_pagina(caminho_pdf: Path) -> dict[int, list[str]]:
    """Títulos do sumário (bookmarks) do PDF agrupados por página (1-based)."""
    with pymupdf.open(caminho_pdf) as documento:
        sumario = documento.get_toc(simple=True)
    por_pagina: dict[int, list[str]] = {}
    for _nivel, titulo, pagina in sumario:
        if pagina >= 1:
            por_pagina.setdefault(pagina, []).append(titulo.strip())
    return por_pagina


def cabecalhos_da_pagina(texto: str, titulos_do_sumario: list[str]) -> list[tuple[int, str]]:
    """Posição e texto de cada cabeçalho encontrado na página, em ordem.

    Usa os títulos do sumário quando existem e completa com os cabeçalhos
    reconhecidos por padrão, para que normas sem bookmark também tenham seção.
    """
    encontrados: dict[int, str] = {}
    for titulo in titulos_do_sumario:
        posicao = texto.find(titulo)
        if posicao >= 0 and _normalizar_titulo(titulo):
            encontrados[posicao] = titulo
    for ocorrencia in PADRAO_CABECALHO.finditer(texto):
        encontrados.setdefault(ocorrencia.start(), ocorrencia.group(0))
    return sorted((pos, _normalizar_titulo(t)) for pos, t in encontrados.items() if _normalizar_titulo(t))


def _normalizar_titulo(titulo: str) -> str:
    """Título em uma linha, sem pontuação final e com no máximo 90 caracteres."""
    limpo = re.sub(r"\s+", " ", titulo).strip(" .-–:")
    return limpo[:90]


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------

def carregar_pdf(caminho_pdf: Path, entrada: EntradaManifesto) -> list[Document]:
    """Carrega um PDF página a página com o `PyMuPDFLoader`."""
    paginas = PyMuPDFLoader(str(caminho_pdf)).load()
    sumario = sumario_por_pagina(caminho_pdf)
    documentos = []
    secao_corrente = ""
    for pagina in paginas:
        numero = int(pagina.metadata.get("page", 0)) + 1
        texto = limpar_texto(pagina.page_content)
        if not texto:
            continue
        cabecalhos = cabecalhos_da_pagina(texto, sumario.get(numero, []))
        documentos.append(
            Document(
                page_content=texto,
                metadata={
                    "fonte": Path(entrada.arquivo).stem,
                    "arquivo": entrada.arquivo,
                    "titulo": entrada.titulo,
                    "tipo_fonte": entrada.tipo,
                    "origem": entrada.origem,
                    "pagina": numero,
                    "total_paginas": int(pagina.metadata.get("total_pages", 0)),
                    # A seção que abre a página é a última vista nas anteriores.
                    "secao_inicial": secao_corrente,
                    # Serializado porque o Chroma aceita apenas escalares.
                    "cabecalhos": json.dumps(cabecalhos, ensure_ascii=False),
                },
            )
        )
        if cabecalhos:
            secao_corrente = cabecalhos[-1][1]
    return documentos


def carregar_base(diretorio: Path = DIRETORIO_BASE_CONHECIMENTO) -> list[Document]:
    """Carrega todos os PDFs declarados no manifesto."""
    diretorio = Path(diretorio)
    manifesto = ler_manifesto(diretorio)
    presentes = {p.name for p in diretorio.glob("*.pdf")}

    sem_manifesto = presentes - set(manifesto)
    if sem_manifesto:
        raise ValueError(
            "PDFs sem procedência declarada em manifesto.json: " + ", ".join(sorted(sem_manifesto))
        )
    ausentes = set(manifesto) - presentes
    if ausentes:
        raise FileNotFoundError("PDFs do manifesto ausentes: " + ", ".join(sorted(ausentes)))

    documentos: list[Document] = []
    for arquivo in sorted(manifesto):
        documentos.extend(carregar_pdf(diretorio / arquivo, manifesto[arquivo]))
    return documentos
