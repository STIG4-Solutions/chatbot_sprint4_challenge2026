"""
Núcleo conversacional em LCEL: `prompt | llm | parser` (Aula 01).

Nas Sprints 1 e 2 o núcleo era imperativo: uma função montava manualmente a
lista de mensagens (system, few-shot, histórico, pergunta), chamava o cliente do
provedor e devolvia a string bruta. Prompt, orquestração, recuperação de contexto
e cliente de inferência estavam no mesmo bloco de código, o que tornava inviável
trocar qualquer um deles isoladamente ou medir a contribuição de cada etapa.

Este módulo reconstrói esse núcleo como uma chain LCEL declarativa:

    ChatPromptTemplate | ChatOllama | PydanticOutputParser

Cada etapa vira um `Runnable` componível, o system prompt passa a ser um artefato
versionado carregado de `prompts/`, e a saída passa por um parser que valida o
contrato de dados definido em `src/schemas/consulta_recarga.py`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough
from langchain_ollama import ChatOllama

from src.config import DIRETORIO_PROMPTS, Configuracao, ParametrosModelo, carregar_configuracao
from src.rag.knowledge_base import recuperar_contexto
from src.schemas.consulta_recarga import ConsultaRecarga
from src.telemetry.tokens import ChatOllamaMensurado

VERSAO_PROMPT_PADRAO = "v3"
CHAVE_HISTORICO = "historico"
CHAVE_PERGUNTA = "pergunta"

GABARITO_CONTEXTO = (
    "<contexto_tecnico>\n{contexto_tecnico}\n</contexto_tecnico>"
)


# ---------------------------------------------------------------------------
# System prompt versionado
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8)
def carregar_system_prompt(versao: str = VERSAO_PROMPT_PADRAO) -> str:
    """Lê `prompts/system_prompt_<versao>.md`.

    O prompt é um artefato do repositório, não uma constante de código: cada
    versão é um arquivo próprio, comparável em diff e rastreável em
    `prompts/VERSIONS.md`.
    """
    arquivo = Path(DIRETORIO_PROMPTS) / f"system_prompt_{versao}.md"
    if not arquivo.exists():
        disponiveis = sorted(p.stem for p in Path(DIRETORIO_PROMPTS).glob("system_prompt_*.md"))
        raise FileNotFoundError(
            f"versão de prompt '{versao}' não encontrada. Disponíveis: {disponiveis}"
        )
    return arquivo.read_text(encoding="utf-8").strip()


def versoes_de_prompt_disponiveis() -> list[str]:
    return sorted(
        arquivo.stem.replace("system_prompt_", "")
        for arquivo in Path(DIRETORIO_PROMPTS).glob("system_prompt_*.md")
    )


# ---------------------------------------------------------------------------
# Cliente de inferência
# ---------------------------------------------------------------------------

def criar_llm(
    parametros: ParametrosModelo,
    configuracao: Configuracao | None = None,
    raciocinio: str | None = None,
) -> ChatOllama:
    """Instancia o `ChatOllama` apontado para o endpoint configurado.

    O tipo concreto é `ChatOllamaMensurado`, subclasse de `ChatOllama` que
    preserva integralmente o comportamento de inferência e substitui apenas a
    contagem de tokens pelo vocabulário correto do modelo. Ver
    `src/telemetry/tokens.py`. Para todos os efeitos da chain, é um `ChatOllama`.

    A credencial viaja apenas no cabeçalho `Authorization`, montado em tempo de
    execução a partir da variável de ambiente.

    `raciocinio` define o esforço de raciocínio dos modelos que o expõem
    (`gpt-oss`: "low", "medium", "high"). Nas chamadas auxiliares curtas do
    RAG (expansão de consulta e reranking) usa-se "low": com o padrão, o
    raciocínio consome todo o `num_predict` e o conteúdo volta vazio (Sprint 4).
    """
    configuracao = configuracao or carregar_configuracao()
    return ChatOllamaMensurado(
        model=parametros.modelo,
        base_url=configuracao.base_url,
        temperature=parametros.temperature,
        top_p=parametros.top_p,
        num_predict=parametros.num_predict,
        seed=parametros.seed,
        reasoning=raciocinio,
        client_kwargs={
            "headers": {"Authorization": f"Bearer {configuracao.api_key}"},
            "timeout": 180,
        },
    )


# ---------------------------------------------------------------------------
# Prompt e parser
# ---------------------------------------------------------------------------

def criar_parser(estruturado: bool = True):
    """`PydanticOutputParser` quando a saída é contratual, `StrOutputParser`
    quando a versão do prompt ainda produz texto corrido (v1 e v2)."""
    if estruturado:
        return PydanticOutputParser(pydantic_object=ConsultaRecarga)
    return StrOutputParser()


def criar_prompt(versao: str, parser) -> ChatPromptTemplate:
    """Monta o `ChatPromptTemplate` com placeholder de histórico.

    O bloco de contexto recuperado entra como mensagem de sistema separada, de
    modo que a delimitação por marcas XML permaneça íntegra qualquer que seja o
    conteúdo recuperado.
    """
    texto_system = carregar_system_prompt(versao)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", texto_system),
            ("system", GABARITO_CONTEXTO),
            MessagesPlaceholder(variable_name=CHAVE_HISTORICO, optional=True),
            ("human", "{" + CHAVE_PERGUNTA + "}"),
        ]
    )

    if "format_instructions" in prompt.input_variables:
        if not isinstance(parser, PydanticOutputParser):
            raise ValueError(
                f"o prompt '{versao}' declara um contrato de saída estruturada e "
                "exige PydanticOutputParser"
            )
        prompt = prompt.partial(format_instructions=parser.get_format_instructions())

    return prompt


# ---------------------------------------------------------------------------
# Chain LCEL
# ---------------------------------------------------------------------------

def _etapa_recuperacao(entrada: dict) -> str:
    return recuperar_contexto(entrada.get(CHAVE_PERGUNTA, ""))


def construir_chain(
    versao_prompt: str = VERSAO_PROMPT_PADRAO,
    parametros: ParametrosModelo | None = None,
    configuracao: Configuracao | None = None,
    estruturado: bool | None = None,
    com_recuperacao: bool = True,
) -> Runnable:
    """Monta a chain `prompt | llm | parser` do refactory.

    Parâmetros
    ----------
    versao_prompt   versão do system prompt em `prompts/`.
    parametros      modelo e parâmetros de geração documentados no §6.2.
    estruturado     força saída contratual; quando omitido, é inferido da
                    presença do contrato na versão do prompt.
    com_recuperacao liga a etapa de recuperação de contexto técnico.
    """
    configuracao = configuracao or carregar_configuracao()
    parametros = parametros or ParametrosModelo(modelo=configuracao.modelo_primario)

    if estruturado is None:
        estruturado = "{format_instructions}" in carregar_system_prompt(versao_prompt)

    parser = criar_parser(estruturado)
    prompt = criar_prompt(versao_prompt, parser)
    llm = criar_llm(parametros, configuracao)

    if estruturado:
        # Restringe a decodificação a JSON sintaticamente válido, deixando ao
        # parser a validação semântica do schema.
        llm = llm.bind(format="json")

    if com_recuperacao:
        etapa_contexto = RunnablePassthrough.assign(
            contexto_tecnico=RunnableLambda(_etapa_recuperacao)
        )
    else:
        etapa_contexto = RunnablePassthrough.assign(
            contexto_tecnico=RunnableLambda(lambda _: "")
        )

    return etapa_contexto | prompt | llm | parser
