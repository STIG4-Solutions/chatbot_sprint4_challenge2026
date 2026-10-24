"""
Chamada multi-provider (bônus da Sprint 4): mais de um modelo e mais de um prompt.

A mesma pergunta é recuperada uma única vez e o mesmo contexto é enviado a
cada combinação de modelo e versão de prompt RAG, em paralelo. Fixar o
contexto isola o efeito do modelo e do prompt: a diferença entre as respostas
não pode ser atribuída à recuperação.

Provedores:
- Ollama Cloud, que serve modelos de fabricantes distintos pela mesma API
  (OpenAI gpt-oss, Google Gemma, Mistral, DeepSeek, Moonshot Kimi);
- OpenAI, via `langchain-openai`, habilitado apenas se `OPENAI_API_KEY`
  estiver definida no ambiente. É o provedor das Sprints 1 e 2.

Cada fabricante treina e alinha o modelo de forma independente, e é isso que a
comparação mede. Nenhuma credencial é lida fora de `src/config.py` e do
ambiente.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from pydantic import ValidationError

from src.chain.builder import criar_llm
from src.config import ParametrosModelo, carregar_configuracao
from src.guardrails.moderation import avaliar_entrada
from src.guardrails.scope_validator import validar_entrada
from src.rag.pipeline import _extrair_json
from src.rag.prompt_rag import criar_prompt_rag, formatar_contexto
from src.rag.retriever import ParametrosRecuperacao, Recuperador
from src.schemas.resposta_rag import RespostaRAG

FABRICANTES = {
    "gpt-oss": "OpenAI (open-weight)",
    "gemma": "Google",
    "mistral": "Mistral AI",
    "deepseek": "DeepSeek",
    "kimi": "Moonshot AI",
    "qwen": "Alibaba",
    "gpt-4o": "OpenAI",
}

TEMPO_MAXIMO_S = 180

PROVEDORES = ["Ollama Cloud"] + (["OpenAI"] if os.getenv("OPENAI_API_KEY") else [])


def fabricante(modelo: str) -> str:
    for prefixo, nome in FABRICANTES.items():
        if modelo.startswith(prefixo):
            return nome
    return "não identificado"


def _llm(modelo: str):
    """Cliente do provedor do modelo: `openai:<modelo>` usa a API da OpenAI."""
    parametros = ParametrosModelo(modelo=modelo.removeprefix("openai:"), temperature=0.0, num_predict=1200, seed=7)
    if modelo.startswith("openai:"):
        from langchain_openai import ChatOpenAI

        return "OpenAI", ChatOpenAI(model=parametros.modelo, temperature=0.0, max_tokens=1200,
                                    model_kwargs={"response_format": {"type": "json_object"}})
    return "Ollama Cloud", criar_llm(parametros, carregar_configuracao()).bind(format="json")


def consultar_matriz(
    pergunta: str,
    modelos: list[str],
    prompts: list[str],
    recuperador: Recuperador | None = None,
) -> list[dict]:
    for avaliar in (avaliar_entrada, validar_entrada):
        veredito = avaliar(pergunta)
        if veredito.bloqueado:
            texto = veredito.resposta.como_texto()
            return [{"provedor": "guardrails", "modelo": "-", "fabricante": "-", "prompt": "-", "resposta": texto,
                     "citacoes": "", "valida": True, "latencia_s": 0.0}]

    recuperador = recuperador or Recuperador(ParametrosRecuperacao(k=6, hibrida=True))
    recuperacao = recuperador.buscar(pergunta)
    contexto = formatar_contexto(recuperacao.trechos)
    formato = PydanticOutputParser(pydantic_object=RespostaRAG).get_format_instructions()

    def chamar(par: tuple[str, str]) -> dict:
        modelo, versao = par
        provedor, llm = _llm(modelo)
        chain = criar_prompt_rag(versao, formato) | llm | StrOutputParser()
        inicio = time.perf_counter()
        try:
            bruto = chain.invoke({"pergunta": pergunta, "contexto": contexto, "historico": []})
            latencia = time.perf_counter() - inicio
            resposta = RespostaRAG.model_validate(_extrair_json(bruto), context={"total_trechos": len(recuperacao.trechos)})
            citacoes = "; ".join(
                f"[{i}] {recuperacao.trechos[i - 1].rotulo_citacao()}" for i in resposta.citacoes
            )
            texto, valida = resposta.resposta, True
        except (ValueError, ValidationError) as excecao:
            latencia = time.perf_counter() - inicio
            texto, citacoes, valida = f"(saída inválida: {type(excecao).__name__})", "", False
        except Exception as excecao:  # transporte ou provedor indisponível
            latencia = time.perf_counter() - inicio
            texto, citacoes, valida = f"(falha do provedor: {type(excecao).__name__})", "", False
        return {"provedor": provedor, "modelo": modelo, "fabricante": fabricante(modelo.removeprefix("openai:")),
                "prompt": versao, "resposta": texto, "citacoes": citacoes, "valida": valida,
                "latencia_s": round(latencia, 2)}

    pares = [(m, p) for m in modelos for p in prompts]
    pool = ThreadPoolExecutor(max_workers=min(4, len(pares)))
    futuros = [pool.submit(chamar, par) for par in pares]
    linhas = []
    for (modelo, versao), futuro in zip(pares, futuros):
        try:
            linhas.append(futuro.result(timeout=TEMPO_MAXIMO_S))
        except Exception:
            # Provedor que não conclui a resposta no prazo entra na tabela
            # como falha, sem travar as demais combinações.
            linhas.append({"provedor": "Ollama Cloud", "modelo": modelo, "fabricante": fabricante(modelo),
                           "prompt": versao, "resposta": f"(sem resposta em {TEMPO_MAXIMO_S} s)", "citacoes": "",
                           "valida": False, "latencia_s": float(TEMPO_MAXIMO_S)})
    pool.shutdown(wait=False, cancel_futures=True)
    return linhas
