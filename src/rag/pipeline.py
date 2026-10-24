"""
Pipeline RAG end-to-end (Aula 06): pergunta, guardrails, recuperação, geração
fundamentada e citação.

    pergunta ─▶ moderação (jailbreak, injeção, domínios com profissional habilitado)
             ─▶ validação de escopo GoodWe
             ─▶ reescrita da pergunta com o histórico (somente em continuação)
             ─▶ chain LCEL: retriever (ChromaDB) ─▶ contexto ─▶ prompt RAG ─▶ LLM
             ─▶ parse e validação do contrato RespostaRAG
             ─▶ validação de especificação de produto sem fundamento
             ─▶ citações montadas em código a partir dos metadados
             ─▶ memória da sessão (orçamento de tokens, herdada da Sprint 3)

Duas recusas acontecem sem chamar o LLM gerador: a dos guardrails de entrada e
a de contexto insuficiente, quando o melhor trecho recuperado fica abaixo do
limiar de relevância. Nos dois casos a recusa é determinística.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough
from pydantic import ValidationError

from src.chain.builder import criar_llm
from src.chain.memoria import LIMITE_TOKENS_PADRAO, RegistroDeSessoes
from src.config import Configuracao, ParametrosModelo, carregar_configuracao
from src.guardrails import Veredito
from src.guardrails.moderation import avaliar_entrada
from src.guardrails.scope_validator import validar_entrada, validar_resposta
from src.rag.prompt_rag import (
    CHAVE_CONTEXTO,
    CHAVE_HISTORICO,
    CHAVE_PERGUNTA,
    VERSAO_PADRAO,
    criar_prompt_rag,
    formatar_contexto,
)
from src.rag.retriever import (
    ParametrosRecuperacao,
    Recuperador,
    ResultadoRecuperacao,
    TrechoRecuperado,
    _rotulo_secao,
)
from src.rag.vector_store import ConfiguracaoIndice
from src.schemas.consulta_recarga import CategoriaConsulta
from src.schemas.resposta_rag import RespostaRAG
from src.telemetry.tokens import CONTADOR, Medicao, RegistradorDeTokens, cronometrar

SESSAO_PADRAO = "operador-local"
TENTATIVAS_DE_PARSE = 2

MENSAGEM_SEM_CONTEXTO = (
    "A informação pedida não está na base de conhecimento do ChargeGrid. "
    "Para não responder com suposição, nenhuma resposta foi gerada. "
    "Consulte o documento de origem (datasheet do modelo, fatura da distribuidora "
    "ou registro da sessão) ou peça a inclusão dele na base."
)

PROMPT_REESCRITA = (
    "Reescreva a última pergunta do operador como uma pergunta autônoma, "
    "completa e em português, substituindo pronomes e referências ao que foi "
    "dito antes pelos termos explícitos. Não responda à pergunta. Devolva só a "
    "pergunta reescrita.\n\nHistórico:\n{historico}\n\nÚltima pergunta: {pergunta}"
)


# ---------------------------------------------------------------------------
# Resultado de um turno
# ---------------------------------------------------------------------------

@dataclass
class Citacao:
    id: int
    documento: str
    pagina: int
    localizacao: str
    tipo_fonte: str
    arquivo: str
    trecho: str

    def rotulo(self) -> str:
        return f"[{self.id}] {self.documento}, p. {self.pagina}" + (
            f", {self.localizacao}" if self.localizacao else ""
        )


@dataclass
class ResultadoRAG:
    pergunta: str
    consulta_recuperacao: str
    texto: str
    estruturado: RespostaRAG | None
    citacoes: list[Citacao]
    recuperacao: ResultadoRecuperacao | None
    medicao: Medicao
    veredito: Veredito = field(default_factory=Veredito.liberado)
    estagio: str = "rag"
    erro: str | None = None

    @property
    def interceptado(self) -> bool:
        return self.estagio != "rag"

    @property
    def contextos(self) -> list[str]:
        """Textos recuperados, na forma exigida pelo RAGAS (retrieved_contexts)."""
        if not self.recuperacao:
            return []
        return [t.documento.page_content for t in self.recuperacao.trechos]

    def texto_com_fontes(self) -> str:
        if not self.citacoes:
            return self.texto
        fontes = "\n".join(f"- {c.rotulo()}" for c in self.citacoes)
        return f"{self.texto}\n\nFontes:\n{fontes}"

    def como_dicionario(self) -> dict:
        return {
            "pergunta": self.pergunta,
            "consulta_recuperacao": self.consulta_recuperacao,
            "texto": self.texto,
            "estruturado": self.estruturado.model_dump(mode="json") if self.estruturado else None,
            "citacoes": [c.__dict__ for c in self.citacoes],
            "trechos": [t.como_dicionario() for t in self.recuperacao.trechos] if self.recuperacao else [],
            "melhor_relevancia": self.recuperacao.melhor_relevancia if self.recuperacao else None,
            "estagio": self.estagio,
            "guardrail": self.veredito.como_dicionario(),
            "erro": self.erro,
            **self.medicao.como_dicionario(),
        }


# ---------------------------------------------------------------------------
# Assistente
# ---------------------------------------------------------------------------

def _extrair_json(texto: str) -> dict:
    """Extrai o objeto JSON da saída, tolerando cerca de código residual."""
    limpo = texto.strip()
    limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpo)
    inicio, fim = limpo.find("{"), limpo.rfind("}")
    if inicio < 0 or fim < 0:
        raise ValueError("saída sem objeto JSON")
    return json.loads(limpo[inicio : fim + 1])


class AssistenteRAG:
    """Assistente do operador comercial com RAG fundamentado e citação de fonte."""

    def __init__(
        self,
        versao_prompt: str = VERSAO_PADRAO,
        parametros: ParametrosModelo | None = None,
        parametros_recuperacao: ParametrosRecuperacao | None = None,
        configuracao_indice: ConfiguracaoIndice | None = None,
        configuracao: Configuracao | None = None,
        recuperador: Recuperador | None = None,
        com_guardrails: bool = True,
        reescrever_pergunta: bool = True,
        limite_tokens_memoria: int = LIMITE_TOKENS_PADRAO,
    ) -> None:
        self.configuracao = configuracao or carregar_configuracao()
        # temperature 0 por padrão: a resposta deve ser função do contexto
        # recuperado, não da amostragem (ver docs/relatorio_modelos.md).
        self.parametros = parametros or ParametrosModelo(
            modelo=self.configuracao.modelo_primario, temperature=0.0, num_predict=1200
        )
        self.versao_prompt = versao_prompt
        self.com_guardrails = com_guardrails
        self.reescrever_pergunta = reescrever_pergunta
        self.recuperador = recuperador or Recuperador(
            parametros_recuperacao or ParametrosRecuperacao(),
            configuracao_indice or ConfiguracaoIndice(),
        )
        self.llm = criar_llm(self.parametros, self.configuracao)
        self.parser = PydanticOutputParser(pydantic_object=RespostaRAG)
        self.prompt = criar_prompt_rag(versao_prompt, self.parser.get_format_instructions())
        self.chain = self._construir_chain()
        self.sessoes = RegistroDeSessoes(self.llm, limite_tokens_memoria)

    # -- chain LCEL ----------------------------------------------------------

    def _construir_chain(self) -> Runnable:
        """retriever | contexto | prompt | llm | parser, numa única chain LCEL."""
        geracao = self.prompt | self.llm.bind(format="json") | StrOutputParser()
        return (
            RunnablePassthrough.assign(
                recuperacao=RunnableLambda(lambda e: self.recuperador.buscar(e["consulta"]))
            )
            | RunnablePassthrough.assign(
                **{CHAVE_CONTEXTO: RunnableLambda(lambda e: formatar_contexto(e["recuperacao"].trechos))}
            )
            | RunnablePassthrough.assign(
                saida_bruta=RunnableLambda(
                    lambda e: geracao.invoke(e) if e["recuperacao"].suficiente else None
                )
            )
        )

    # -- turno ---------------------------------------------------------------

    def responder(self, pergunta: str, session_id: str = SESSAO_PADRAO) -> ResultadoRAG:
        medicao = Medicao()
        historico = self.sessoes.obter(session_id)

        if self.com_guardrails:
            for estagio, avaliar in (("moderacao", avaliar_entrada), ("escopo", validar_entrada)):
                veredito = avaliar(pergunta)
                if veredito.bloqueado:
                    return self._recusa_guardrail(pergunta, veredito, estagio, session_id, medicao)

        registrador = RegistradorDeTokens(CONTADOR)
        with cronometrar(medicao):
            consulta = self._consulta_autonoma(pergunta, historico.messages, registrador)
            estruturado, saida, erro = None, None, None
            for tentativa in range(TENTATIVAS_DE_PARSE):
                saida = self.chain.invoke(
                    {CHAVE_PERGUNTA: pergunta, "consulta": consulta, CHAVE_HISTORICO: historico.messages},
                    config={"callbacks": [registrador]},
                )
                if saida["saida_bruta"] is None:
                    break
                try:
                    estruturado = RespostaRAG.model_validate(
                        _extrair_json(saida["saida_bruta"]),
                        context={"total_trechos": len(saida["recuperacao"].trechos)},
                    )
                    erro = None
                    break
                except (ValueError, ValidationError) as excecao:
                    erro = f"{type(excecao).__name__}: {str(excecao)[:300]}"

        recuperacao: ResultadoRecuperacao = saida["recuperacao"]
        medicao.tokens_entrada = registrador.tokens_entrada

        if not recuperacao.suficiente:
            resultado = ResultadoRAG(
                pergunta, consulta, MENSAGEM_SEM_CONTEXTO, None, [], recuperacao, medicao,
                estagio="sem_contexto",
            )
        elif estruturado is None:
            resultado = ResultadoRAG(
                pergunta, consulta,
                "Não foi possível produzir uma resposta fundamentada e aderente ao contrato de saída.",
                None, [], recuperacao, medicao, estagio="erro_de_contrato", erro=erro,
            )
        else:
            resultado = self._resultado_gerado(pergunta, consulta, estruturado, recuperacao, medicao)

        medicao.tokens_saida = CONTADOR.contar_texto(resultado.texto)
        historico.add_messages([HumanMessage(content=pergunta), AIMessage(content=resultado.texto)])
        return resultado

    def _consulta_autonoma(self, pergunta: str, mensagens: list, registrador) -> str:
        """Reescreve a pergunta de continuação ("e nesse horário?") para a busca.

        Sem histórico a pergunta vai para o retriever como está. Com histórico,
        uma chamada curta ao LLM resolve as referências, porque o embedding de
        "e se forem quatro carros?" não recupera nada útil sozinho.
        """
        if not self.reescrever_pergunta or not mensagens:
            return pergunta
        historico = "\n".join(
            f"{'Operador' if isinstance(m, HumanMessage) else 'Assistente'}: {m.content[:400]}"
            for m in mensagens[-4:]
        )
        try:
            reescrita = self.llm.invoke(
                PROMPT_REESCRITA.format(historico=historico, pergunta=pergunta),
                config={"callbacks": [registrador]},
            ).content.strip()
        except Exception:
            return pergunta
        return reescrita or pergunta

    def _resultado_gerado(
        self,
        pergunta: str,
        consulta: str,
        estruturado: RespostaRAG,
        recuperacao: ResultadoRecuperacao,
        medicao: Medicao,
    ) -> ResultadoRAG:
        trechos = recuperacao.trechos
        citacoes = [self._citacao(i, trechos[i - 1]) for i in estruturado.citacoes]

        if self.com_guardrails and estruturado.dentro_do_escopo:
            contexto = " ".join(t.documento.page_content for t in trechos)
            veredito = validar_resposta(estruturado.texto_sem_marcadores(), contexto)
            if veredito.bloqueado:
                return ResultadoRAG(
                    pergunta, consulta, veredito.resposta.como_texto(), None, [], recuperacao,
                    medicao, veredito=veredito, estagio="validacao_da_resposta",
                )
        return ResultadoRAG(pergunta, consulta, estruturado.resposta, estruturado, citacoes, recuperacao, medicao)

    @staticmethod
    def _citacao(indice: int, trecho: TrechoRecuperado) -> Citacao:
        m = trecho.metadados
        if m.get("artigos"):
            localizacao = ("Art. " if "," not in m["artigos"] else "Arts. ") + m["artigos"]
        else:
            localizacao = _rotulo_secao(m.get("secao", ""))
        return Citacao(
            id=indice,
            documento=m.get("titulo", ""),
            pagina=int(m.get("pagina", 0)),
            localizacao=localizacao,
            tipo_fonte=m.get("tipo_fonte", ""),
            arquivo=m.get("arquivo", ""),
            trecho=trecho.documento.page_content,
        )

    def _recusa_guardrail(
        self, pergunta: str, veredito: Veredito, estagio: str, session_id: str, medicao: Medicao
    ) -> ResultadoRAG:
        texto = veredito.resposta.como_texto()
        medicao.tokens_entrada = CONTADOR.contar_texto(pergunta)
        medicao.tokens_saida = CONTADOR.contar_texto(texto)
        self.sessoes.obter(session_id).add_messages(
            [HumanMessage(content=pergunta), AIMessage(content=texto)]
        )
        categoria = veredito.resposta.categoria
        estruturado = RespostaRAG(
            resposta=texto,
            citacoes=[],
            contexto_suficiente=False,
            categoria=categoria if categoria else CategoriaConsulta.FORA_DE_ESCOPO,
            dentro_do_escopo=False,
        )
        return ResultadoRAG(pergunta, pergunta, texto, estruturado, [], None, medicao, veredito, estagio)

    # -- sessão --------------------------------------------------------------

    def estado_da_sessao(self, session_id: str = SESSAO_PADRAO) -> dict:
        historico = self.sessoes.obter(session_id)
        return {
            "session_id": session_id,
            "mensagens": len(historico.messages),
            "tokens_em_uso": historico.tokens_em_uso(),
            "limite_tokens": historico.limite_tokens,
        }

    def reiniciar_sessao(self, session_id: str = SESSAO_PADRAO) -> None:
        self.sessoes.obter(session_id).clear()
