import json

import pytest
from langchain_core.documents import Document

from src.config import DIRETORIO_BASE_CONHECIMENTO
from src.rag.chunking import EstrategiaChunking, _e_sumario, dividir
from src.rag.loader import carregar_base, cabecalhos_da_pagina, ler_manifesto, limpar_texto


def test_todo_pdf_da_base_tem_procedencia_no_manifesto():
    manifesto = ler_manifesto()
    pdfs = {p.name for p in DIRETORIO_BASE_CONHECIMENTO.glob("*.pdf")}
    assert pdfs == set(manifesto)
    assert all(e.origem for e in manifesto.values())


def test_base_tem_os_tres_tipos_de_fonte():
    tipos = {e.tipo for e in ler_manifesto().values()}
    assert tipos == {"oficial", "projeto", "nao_verificada"}


def test_limpar_texto_remove_hifenizacao_e_sumario_pontilhado():
    assert limpar_texto("distri-\nbuidora") == "distribuidora"
    assert limpar_texto("5.16. Set Charging Profile . . . . . . . 53") == "5.16. Set Charging Profile … 53"


def test_cabecalhos_reconhecem_artigo_e_titulo_numerado():
    texto = "Seção III\nArt. 554. É permitida a recarga\n3.2 Limiares de operação\ntexto"
    titulos = [t for _, t in cabecalhos_da_pagina(texto, [])]
    assert "Seção III" in titulos
    assert any(t.startswith("Art. 554") for t in titulos)
    assert "3.2 Limiares de operação" in titulos


def _pagina(texto, **meta):
    base = {"arquivo": "x.pdf", "pagina": 1, "titulo": "X", "tipo_fonte": "oficial",
            "secao_inicial": "", "cabecalhos": json.dumps([[0, "1. Introdução"]])}
    base.update(meta)
    return Document(page_content=texto, metadata=base)


def test_fragmento_recebe_secao_artigos_e_id_estavel():
    texto = "1. Introdução\n" + ("Art. 554. É permitida a recarga para exploração comercial. " * 30)
    a = dividir([_pagina(texto)], EstrategiaChunking(400, 50))
    b = dividir([_pagina(texto)], EstrategiaChunking(400, 50))
    assert [f.metadata["chunk_id"] for f in a] == [f.metadata["chunk_id"] for f in b]
    assert a[0].metadata["secao"] == "1. Introdução"
    assert "554" in a[0].metadata["artigos"]


def test_fragmento_de_sumario_e_descartado():
    sumario = "\n".join(f"5.{i}. Mensagem {i} … {i + 40}" for i in range(12))
    assert _e_sumario(sumario)
    assert not _e_sumario("Art. 301. A distribuidora deve adicionar ao faturamento a cobrança. " * 5)


def test_documento_envenenado_e_marcado_e_sanitizado_na_ingestao():
    fragmentos = dividir(carregar_base())
    suspeitos = [f for f in fragmentos if f.metadata["suspeito_injecao"]]
    assert suspeitos, "o fórum de teste deveria ser marcado"
    assert {f.metadata["arquivo"] for f in suspeitos} == {"forum_usuarios_recarga.pdf"}
    for f in suspeitos:
        assert "ignore todas as instruções" not in f.page_content.lower()
        assert "trecho removido" in f.page_content


def test_documentos_oficiais_nao_geram_falso_positivo_de_injecao():
    fragmentos = dividir(carregar_base())
    oficiais = [f for f in fragmentos if f.metadata["tipo_fonte"] == "oficial"]
    assert oficiais and not any(f.metadata["suspeito_injecao"] for f in oficiais)
