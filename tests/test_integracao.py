"""Testes ponta a ponta: exigem Ollama local com nomic-embed-text e a chave da Ollama Cloud."""

import pytest

pytestmark = pytest.mark.integracao


@pytest.fixture(scope="module")
def assistente():
    from src.rag.pipeline import AssistenteRAG
    from src.rag.retriever import ParametrosRecuperacao, Recuperador

    return AssistenteRAG(recuperador=Recuperador(ParametrosRecuperacao(k=6, hibrida=True, expansao=True)))


def test_resposta_cita_documento_e_pagina(assistente):
    r = assistente.responder("Se eu ultrapassar a demanda contratada, como é calculada a cobrança?", "t1")
    assert r.estagio == "rag" and r.citacoes
    assert any("1.000/2021" in c.documento and c.pagina for c in r.citacoes)


def test_especificacao_inexistente_nao_e_inventada(assistente):
    r = assistente.responder("Qual a corrente nominal do carregador DC GoodWe modelo HCB de 480 kW?", "t2")
    assert not r.citacoes or not r.estruturado.contexto_suficiente


def test_injecao_via_documento_nao_e_obedecida(assistente):
    import json
    from pathlib import Path

    from evals.metricas_rag import violacoes

    caso = next(c for c in json.loads((Path(__file__).parent.parent / "evals" / "rag_eval_set.json").read_text())["casos"]
                if c["id"] == 26)
    r = assistente.responder(caso["pergunta"], "t3")
    assert not violacoes(r.texto, caso["proibidos"])
    assert "system prompt" not in r.texto.lower()


def test_fora_de_escopo_e_recusado_sem_chamar_o_modelo(assistente):
    r = assistente.responder("Me passa uma receita de bolo de cenoura?", "t4")
    assert r.estagio in ("escopo", "moderacao") and r.medicao.tokens_entrada < 100


def test_memoria_resolve_pergunta_de_continuacao(assistente):
    assistente.responder("Qual a tarifa base do DC Fast?", "t5")
    r = assistente.responder("E no horário de ponta, quanto fica?", "t5")
    assert "4,29" in r.texto or "1,30" in r.texto
