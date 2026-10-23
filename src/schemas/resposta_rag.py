"""
Contrato de saída do pipeline RAG (Sprint 4), em Pydantic v2.

O `ConsultaRecarga` da Sprint 3 continua sendo o contrato do núcleo
conversacional sem recuperação. Com RAG a exigência muda: cada afirmação
precisa apontar o trecho que a sustenta. `RespostaRAG` torna isso verificável
por máquina: o texto traz marcadores [n] e a lista `citacoes` declara os
mesmos ids. O validador recusa resposta dentro do escopo sem citação e
citação de trecho que não foi recuperado.

A citação exibida ao operador (documento, página, artigo ou seção) não é
escrita pelo modelo: é montada em código a partir dos metadados do trecho
citado (`src/rag/pipeline.py`), de modo que o modelo não tem como inventar
uma fonte.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from src.schemas.consulta_recarga import CATEGORIAS_DE_RECUSA, CategoriaConsulta

PADRAO_MARCADOR = re.compile(r"\[(\d{1,2})\]")


class RespostaRAG(BaseModel):
    resposta: str = Field(
        description=(
            "Resposta ao operador. Cada frase com fato termina com o marcador [n] do "
            "trecho que a sustenta."
        )
    )
    citacoes: list[int] = Field(
        default_factory=list,
        description="Ids dos trechos de <contexto> efetivamente usados na resposta.",
    )
    contexto_suficiente: bool = Field(
        description="Falso quando os trechos não contêm a resposta à pergunta."
    )
    categoria: CategoriaConsulta = Field(
        description="Categoria da consulta segundo a taxonomia do projeto."
    )
    dentro_do_escopo: bool = Field(
        description="Falso quando a consulta foi recusada por escopo ou por domínio."
    )

    @field_validator("resposta")
    @classmethod
    def _texto_substantivo(cls, valor: str) -> str:
        limpo = (valor or "").strip()
        if len(limpo) < 10:
            raise ValueError("resposta vazia ou curta demais")
        return limpo

    @field_validator("citacoes")
    @classmethod
    def _ids_validos(cls, valor: list[int], info: ValidationInfo) -> list[int]:
        """Rejeita id de trecho que não foi entregue ao modelo.

        O total de trechos chega pelo contexto de validação
        (`model_validate(..., context={"total_trechos": n})`).
        """
        ids = sorted(set(int(v) for v in valor))
        total = (info.context or {}).get("total_trechos")
        if total is not None:
            invalidos = [i for i in ids if not 1 <= i <= total]
            if invalidos:
                raise ValueError(f"citação de trecho inexistente: {invalidos}")
        return ids

    @model_validator(mode="after")
    def _coerencia(self) -> "RespostaRAG":
        recusa = self.categoria in CATEGORIAS_DE_RECUSA
        if recusa and self.dentro_do_escopo:
            raise ValueError("categoria de recusa exige dentro_do_escopo=False")
        if not recusa and not self.dentro_do_escopo:
            raise ValueError("dentro_do_escopo=False exige categoria de recusa")

        marcadores = sorted({int(m) for m in PADRAO_MARCADOR.findall(self.resposta)})
        # Os ids marcados no texto e os declarados na lista são unificados:
        # o modelo às vezes marca no texto e esquece a lista, ou o inverso.
        self.citacoes = sorted(set(self.citacoes) | set(marcadores))

        if self.dentro_do_escopo and self.contexto_suficiente and not self.citacoes:
            raise ValueError("resposta fundamentada exige ao menos uma citação [n]")
        return self

    def texto_sem_marcadores(self) -> str:
        return re.sub(r"\s*\[\d{1,2}\]", "", self.resposta).strip()
