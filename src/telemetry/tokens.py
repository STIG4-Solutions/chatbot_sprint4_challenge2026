"""
Medição de tokens e latência: context engineering (Aula 04, item §3.4 do escopo).

O LangChain, quando um provedor não declara tokenizador próprio, recorre ao
tokenizador GPT-2 obtido da Hugging Face Hub. Isso introduz duas distorções no
projeto: a contagem não corresponde ao vocabulário real do `gpt-oss` e o caminho
crítico passa a depender de rede e de um download externo.

Este módulo resolve ambos medindo com `tiktoken` no encoding `o200k_harmony`,
que é o vocabulário nativo da família `gpt-oss`. A mesma contagem alimenta a
política de memória (`src/chain/memoria.py`) e a coluna "tokens por turno" da
tabela de comparativo antes/depois.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import tiktoken
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_ollama import ChatOllama

ENCODING_PADRAO = "o200k_harmony"

# Sobrecarga fixa por mensagem no formato de chat (delimitadores de papel e de
# fim de turno). Valor conservador, alinhado ao formato harmony do gpt-oss.
TOKENS_POR_MENSAGEM = 4

TENTATIVAS_LIMITE_CONCORRENCIA = 6


# ---------------------------------------------------------------------------
# Contagem
# ---------------------------------------------------------------------------

class ContadorTokens:
    """Contador de tokens determinístico, offline e estável entre execuções."""

    def __init__(self, encoding: str = ENCODING_PADRAO) -> None:
        self.nome_encoding = encoding
        self._encoding = tiktoken.get_encoding(encoding)

    def contar_texto(self, texto: str) -> int:
        return len(self._encoding.encode(texto or ""))

    def contar_mensagens(self, mensagens: Sequence[BaseMessage]) -> int:
        total = 0
        for mensagem in mensagens:
            conteudo = mensagem.content
            if isinstance(conteudo, list):  # conteúdo multimodal/segmentado
                conteudo = "".join(
                    bloco.get("text", "") if isinstance(bloco, dict) else str(bloco)
                    for bloco in conteudo
                )
            total += self.contar_texto(str(conteudo)) + TOKENS_POR_MENSAGEM
        return total


CONTADOR = ContadorTokens()


# ---------------------------------------------------------------------------
# Cliente de inferência instrumentado
# ---------------------------------------------------------------------------

class ChatOllamaMensurado(ChatOllama):
    """`ChatOllama` com contagem de tokens pelo vocabulário correto do modelo.

    Preserva integralmente o comportamento de inferência da classe original:
    é apenas a métrica de tokens que passa a usar `tiktoken` em vez do
    tokenizador GPT-2 baixado da Hugging Face Hub.
    """

    def get_num_tokens(self, text: str) -> int:
        return CONTADOR.contar_texto(text)

    def get_num_tokens_from_messages(
        self, messages: list[BaseMessage], tools: Sequence | None = None
    ) -> int:
        return CONTADOR.contar_mensagens(messages)

    def _generate(self, *args, **kwargs):
        """Inferência com retentativa em limite de concorrência do provedor.

        O tier gratuito da Ollama Cloud responde HTTP 429 ("too many concurrent
        requests") quando o eval, o reranqueador e o juiz do RAGAS disputam a
        mesma conta. A retentativa com espera exponencial evita que um 429
        vire resposta perdida no meio de uma medição (Sprint 4).
        """
        for tentativa in range(TENTATIVAS_LIMITE_CONCORRENCIA):
            try:
                return super()._generate(*args, **kwargs)
            except Exception as excecao:
                limite = "429" in str(excecao) or "too many" in str(excecao).lower()
                if not limite or tentativa == TENTATIVAS_LIMITE_CONCORRENCIA - 1:
                    raise
                time.sleep(min(60, 2 ** (tentativa + 1)))


# ---------------------------------------------------------------------------
# Latência
# ---------------------------------------------------------------------------

@dataclass
class Medicao:
    """Registro de um turno: tokens de entrada, de saída e latência."""

    tokens_entrada: int = 0
    tokens_saida: int = 0
    latencia_segundos: float = 0.0

    @property
    def tokens_totais(self) -> int:
        return self.tokens_entrada + self.tokens_saida

    def como_dicionario(self) -> dict:
        return {
            "tokens_entrada": self.tokens_entrada,
            "tokens_saida": self.tokens_saida,
            "tokens_totais": self.tokens_totais,
            "latencia_segundos": round(self.latencia_segundos, 3),
        }


@contextmanager
def cronometrar(medicao: Medicao):
    """Mede a latência de parede de um turno e grava no registro informado."""
    inicio = time.perf_counter()
    try:
        yield medicao
    finally:
        medicao.latencia_segundos = time.perf_counter() - inicio


def media(valores: Iterable[float]) -> float:
    valores = list(valores)
    return round(sum(valores) / len(valores), 3) if valores else 0.0


# ---------------------------------------------------------------------------
# Captura das mensagens efetivamente enviadas ao modelo
# ---------------------------------------------------------------------------

class RegistradorDeTokens(BaseCallbackHandler):
    """Callback que mede o prompt real montado pela chain.

    Contar tokens a partir do texto da pergunta subestimaria o consumo: o que
    trafega é o system prompt versionado, o contexto recuperado e o histórico da
    sessão. Este handler intercepta as mensagens no momento da chamada, de modo
    que a coluna "tokens por turno" do comparativo reflita o prompt inteiro.
    """

    def __init__(self, contador: ContadorTokens | None = None) -> None:
        self.contador = contador or CONTADOR
        self.tokens_entrada = 0
        self.ultima_chamada: list[BaseMessage] = []

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:  # noqa: D102
        if not messages:
            return
        self.ultima_chamada = list(messages[0])
        self.tokens_entrada = self.contador.contar_mensagens(self.ultima_chamada)

    def reiniciar(self) -> None:
        self.tokens_entrada = 0
        self.ultima_chamada = []
