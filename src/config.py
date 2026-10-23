"""
Configuração central do ChargeGrid Intelligence (Sprints 3 e 4).

Concentra a leitura das variáveis de ambiente e a construção do cliente de
inferência, de modo que nenhum outro módulo precise conhecer credenciais ou
endpoints. Nenhum valor sensível é definido em código: tudo vem do arquivo
`.env`, que está no `.gitignore`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DIRETORIO_PROMPTS = RAIZ_PROJETO / "prompts"
DIRETORIO_EVALS = RAIZ_PROJETO / "evals"
DIRETORIO_DOCS = RAIZ_PROJETO / "docs"
DIRETORIO_BASE_CONHECIMENTO = RAIZ_PROJETO / "data" / "knowledge_base"
DIRETORIO_PROMPTS_RAG = DIRETORIO_PROMPTS / "rag"
DIRETORIO_CHROMA = RAIZ_PROJETO / ".chroma"

load_dotenv(RAIZ_PROJETO / ".env")


# ---------------------------------------------------------------------------
# Parâmetros de geração
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParametrosModelo:
    """Parâmetros de geração documentados no relatório de modelos (§6.2).

    temperature  : dispersão da amostragem. Mantida baixa porque o assistente
                   produz orientação operacional e regulatória, onde variação
                   de conteúdo entre execuções é indesejável.
    top_p        : massa de probabilidade acumulada considerada na amostragem.
    seed         : semente de amostragem. Mantida nula na operação e fixada na
                   execução do eval, para que o comparativo antes/depois seja
                   reproduzível a partir do repositório.
    num_predict  : teto de tokens de saída (equivalente a `max_tokens`). Fixado
                   em 1400 após medição: a resposta estruturada típica consome
                   cerca de 950 tokens, e um teto inferior trunca o JSON antes
                   do fechamento, invalidando o contrato de saída.
    """

    modelo: str
    temperature: float = 0.2
    top_p: float = 0.9
    num_predict: int = 1400
    seed: int | None = None

    def como_dicionario(self) -> dict:
        return {
            "modelo": self.modelo,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.num_predict,
            "seed": self.seed,
        }


# ---------------------------------------------------------------------------
# Configuração do ambiente
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Configuracao:
    # `repr=False` impede que a credencial apareça se o objeto for impresso em
    # depuração, em log ou em traceback. A chave só é lida no ponto em que o
    # cabeçalho de autenticação é montado.
    api_key: str = field(repr=False)
    base_url: str
    modelo_primario: str
    modelo_alternativo: str
    modelo_terceiro: str
    # Embeddings (Sprint 4). A Ollama Cloud expõe apenas inferência de chat:
    # `/api/embed` responde 401 e `/v1/embeddings` responde 404 com a mesma
    # chave que autentica o chat. O `nomic-embed-text` roda, portanto, no
    # servidor Ollama local, configurável por variável de ambiente.
    embeddings_base_url: str = "http://localhost:11434"
    modelo_embeddings: str = "nomic-embed-text"
    diretorio_chroma: str = str(DIRETORIO_CHROMA)
    limite_tokens_memoria: int = 1200
    encoding_tiktoken: str = "o200k_harmony"
    prompt_padrao: str = "v3"
    tags_ativas: tuple[str, ...] = field(default_factory=tuple)


def carregar_configuracao() -> Configuracao:
    """Lê o ambiente e valida a presença da credencial.

    Levanta `EnvironmentError` com instrução acionável quando a chave não está
    definida. O sistema nunca cai em um valor embutido no código.
    """
    api_key = os.getenv("OLLAMA_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "OLLAMA_API_KEY não encontrada. Copie o arquivo .env.example para .env "
            "e preencha a chave gerada em https://ollama.com/settings/keys."
        )

    return Configuracao(
        api_key=api_key,
        base_url=os.getenv("OLLAMA_BASE_URL", "https://ollama.com").strip(),
        modelo_primario=os.getenv("OLLAMA_MODEL", "gpt-oss:120b").strip(),
        modelo_alternativo=os.getenv("OLLAMA_MODEL_ALT", "gpt-oss:20b").strip(),
        modelo_terceiro=os.getenv("OLLAMA_MODEL_ALT2", "gemma4:31b").strip(),
        embeddings_base_url=os.getenv("OLLAMA_EMBED_BASE_URL", "http://localhost:11434").strip(),
        modelo_embeddings=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text").strip(),
        diretorio_chroma=os.getenv("CHROMA_DIR", str(DIRETORIO_CHROMA)).strip(),
    )


def parametros_padrao(configuracao: Configuracao | None = None) -> ParametrosModelo:
    configuracao = configuracao or carregar_configuracao()
    return ParametrosModelo(modelo=configuracao.modelo_primario)
