"""
Interface web do ChargeGrid Intelligence (Aula 08): Gradio sobre o pipeline RAG.

Uso, a partir da raiz do repositório:
    python -m app.app                 # http://127.0.0.1:7860

Abas:
    Assistente        chat com memória por sessão, citação de fonte em cada
                      resposta, trechos recuperados e diagnóstico do turno
    Comparar          a mesma pergunta em vários modelos e versões de prompt
                      (chamada multi-provider, bônus da sprint)
    Base              documentos indexados, tipo de fonte e procedência
"""

from __future__ import annotations

import html
import os
import sys
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import gradio as gr  # noqa: E402

from src.config import ParametrosModelo, carregar_configuracao  # noqa: E402
from src.multiprovider import PROVEDORES, consultar_matriz  # noqa: E402
from src.rag.loader import ler_manifesto  # noqa: E402
from src.rag.pipeline import AssistenteRAG, ResultadoRAG  # noqa: E402
from src.rag.prompt_rag import versoes_disponiveis  # noqa: E402
from src.rag.retriever import ParametrosRecuperacao, Recuperador  # noqa: E402
from src.rag.vector_store import ConfiguracaoIndice, abrir_indice, todos_os_fragmentos  # noqa: E402

CONFIGURACAO = carregar_configuracao()
MODELOS = [CONFIGURACAO.modelo_primario, CONFIGURACAO.modelo_terceiro, CONFIGURACAO.modelo_alternativo]
ROTULO_TIPO = {"oficial": "oficial", "projeto": "projeto ChargeGrid", "nao_verificada": "não verificada"}

EXEMPLOS = [
    "Tenho 200 kW contratados e a loja consome 170 kW na sexta à noite. Quanto sobra para os carregadores?",
    "Posso cobrar mais caro pela recarga no horário de pico? É legal?",
    "Se eu ultrapassar a demanda contratada, como a distribuidora calcula a cobrança?",
    "Qual a potência e o protocolo de comunicação do GoodWe HCA G2?",
    "Vi num fórum que a recarga nos eletropostos ChargeGrid é gratuita. É verdade?",
    "Qual a potência do carregador DC GoodWe modelo HCB de 480 kW?",
]

_trava = threading.Lock()


@lru_cache(maxsize=8)
def _assistente(modelo: str, prompt: str, k: int, hibrida: bool, expansao: bool, rerank: bool) -> AssistenteRAG:
    recuperador = Recuperador(
        ParametrosRecuperacao(k=k, hibrida=hibrida, expansao=expansao, rerank=rerank),
        ConfiguracaoIndice(),
        loja=abrir_indice(ConfiguracaoIndice(), CONFIGURACAO),
    )
    parametros = ParametrosModelo(modelo=modelo, temperature=0.0, num_predict=1200)
    return AssistenteRAG(prompt, parametros, recuperador=recuperador, configuracao=CONFIGURACAO)


# ---------------------------------------------------------------------------
# Renderização
# ---------------------------------------------------------------------------

def _mensagem_assistente(r: ResultadoRAG) -> str:
    if not r.citacoes:
        return r.texto
    fontes = "\n".join(
        f"- **[{c.id}]** {html.escape(c.documento)}, p. {c.pagina}"
        + (f", {html.escape(c.localizacao)}" if c.localizacao else "")
        + f" · _{ROTULO_TIPO.get(c.tipo_fonte, c.tipo_fonte)}_"
        for c in r.citacoes
    )
    return f"{r.texto}\n\n**Fontes**\n{fontes}"


def _painel_fontes(r: ResultadoRAG) -> str:
    if r.estagio in ("moderacao", "escopo"):
        return f"**Interceptado pelos guardrails** ({r.veredito.categoria.value if r.veredito.categoria else r.estagio}). Nenhum documento consultado e nenhuma chamada ao modelo."
    if r.estagio == "sem_contexto":
        return (f"**Sem contexto suficiente.** Melhor relevância recuperada: {r.recuperacao.melhor_relevancia:.3f}, "
                f"abaixo do limiar de {r.recuperacao.parametros.limiar_relevancia:.2f}. O modelo não foi chamado.")
    if not r.citacoes:
        return "_A resposta não cita trechos: a base não contém a informação pedida ou a pergunta foi recusada._"
    blocos = []
    for c in r.citacoes:
        corrido = " ".join(c.trecho.split())
        trecho = html.escape(corrido[:600]) + ("…" if len(corrido) > 600 else "")
        blocos.append(
            f"**[{c.id}] {html.escape(c.documento)}**  \n"
            f"p. {c.pagina}{' · ' + html.escape(c.localizacao) if c.localizacao else ''} · {ROTULO_TIPO.get(c.tipo_fonte, c.tipo_fonte)} · `{c.arquivo}`\n\n"
            f"> {trecho}"
        )
    return "\n\n---\n\n".join(blocos)


def _tabela_trechos(r: ResultadoRAG) -> list[list]:
    if not r.recuperacao:
        return []
    citados = {c.id for c in r.citacoes}
    return [
        [i, t.metadados.get("titulo"), t.metadados.get("pagina"), round(t.relevancia, 3),
         "sim" if i in citados else "", "sim" if t.metadados.get("suspeito_injecao") else ""]
        for i, t in enumerate(r.recuperacao.trechos, start=1)
    ]


def _diagnostico(r: ResultadoRAG, assistente: AssistenteRAG, sessao: str) -> str:
    m = r.medicao.como_dicionario()
    estado = assistente.estado_da_sessao(sessao)
    linhas = [
        f"- **Estágio:** `{r.estagio}`",
        f"- **Guardrail:** {r.veredito.categoria.value if r.veredito.categoria else 'liberado'}",
        f"- **Modelo:** `{assistente.parametros.modelo}` · prompt `{assistente.versao_prompt}` · temperature {assistente.parametros.temperature}",
        f"- **Tokens:** {m['tokens_entrada']} entrada + {m['tokens_saida']} saída · **latência** {m['latencia_segundos']:.2f} s",
        f"- **Memória:** {estado['mensagens']} mensagens, {estado['tokens_em_uso']} de {estado['limite_tokens']} tokens",
    ]
    if r.consulta_recuperacao and r.consulta_recuperacao != r.pergunta:
        linhas.append(f"- **Consulta reescrita para a busca:** {html.escape(r.consulta_recuperacao)}")
    if r.erro:
        linhas.append(f"- **Erro de contrato:** {html.escape(r.erro)}")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------

def responder(pergunta, historico, sessao, modelo, prompt, k, hibrida, expansao, rerank):
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return gr.update(), historico, gr.update(), gr.update(), gr.update()
    assistente = _assistente(modelo, prompt, int(k), bool(hibrida), bool(expansao), bool(rerank))
    with _trava:
        resultado = assistente.responder(pergunta, session_id=sessao)
    historico = (historico or []) + [
        {"role": "user", "content": pergunta},
        {"role": "assistant", "content": _mensagem_assistente(resultado)},
    ]
    return "", historico, _painel_fontes(resultado), _tabela_trechos(resultado), _diagnostico(resultado, assistente, sessao)


def nova_sessao():
    return [], str(uuid.uuid4()), "", [], ""


def comparar(pergunta, modelos, prompts):
    pergunta = (pergunta or "").strip()
    if not pergunta or not modelos or not prompts:
        return [], "Informe a pergunta e selecione ao menos um modelo e uma versão de prompt."
    inicio = time.perf_counter()
    linhas = consultar_matriz(pergunta, modelos, prompts)
    tabela = [[l["provedor"], l["modelo"], l["prompt"], l["resposta"], l["citacoes"], l["latencia_s"]] for l in linhas]
    return tabela, f"{len(linhas)} chamadas em {time.perf_counter() - inicio:.1f} s"


def tabela_base() -> list[list]:
    manifesto = ler_manifesto()
    contagem: dict[str, int] = {}
    for f in todos_os_fragmentos(abrir_indice(ConfiguracaoIndice(), CONFIGURACAO)):
        contagem[f.metadata["arquivo"]] = contagem.get(f.metadata["arquivo"], 0) + 1
    return [[e.titulo, ROTULO_TIPO[e.tipo], contagem.get(a, 0), e.origem] for a, e in sorted(manifesto.items())]


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

CSS = """
#cabecalho h1 { margin-bottom: 0; }
#cabecalho p { margin-top: 4px; opacity: .8; }
.fonte-painel { max-height: 560px; overflow-y: auto; }
"""


def construir_interface() -> gr.Blocks:
    with gr.Blocks(title="ChargeGrid Intelligence · RAG") as demo:
        sessao = gr.State(str(uuid.uuid4()))
        gr.Markdown(
            "# ChargeGrid Intelligence\n"
            "Assistente do operador comercial de eletropostos · GoodWe × FIAP · EV Challenge 2026 · "
            "respostas fundamentadas na base de conhecimento, com a fonte citada",
            elem_id="cabecalho",
        )
        with gr.Tab("Assistente"):
            with gr.Row():
                with gr.Column(scale=3):
                    chat = gr.Chatbot(label="Conversa", height=520, placeholder="Pergunte sobre demanda, faturamento, regulação, OCPP, MODBUS ou equipamentos GoodWe.")
                    with gr.Row():
                        entrada = gr.Textbox(placeholder="Digite a pergunta do operador e pressione Enter", show_label=False, scale=5)
                        enviar = gr.Button("Enviar", variant="primary", scale=1)
                    gr.Examples(EXEMPLOS, inputs=entrada, label="Exemplos")
                    limpar = gr.Button("Nova sessão (limpa a memória)")
                with gr.Column(scale=2):
                    gr.Markdown("### Fontes citadas")
                    fontes = gr.Markdown(elem_classes="fonte-painel")
                    with gr.Accordion("Trechos recuperados", open=False):
                        trechos = gr.Dataframe(
                            headers=["#", "documento", "página", "relevância", "citado", "injeção removida"],
                            interactive=False, wrap=True,
                        )
                    with gr.Accordion("Diagnóstico do turno", open=False):
                        diagnostico = gr.Markdown()
                    with gr.Accordion("Configuração", open=False):
                        modelo = gr.Dropdown(MODELOS, value=MODELOS[0], label="Modelo")
                        prompt = gr.Dropdown(versoes_disponiveis(), value="v4", label="Versão do prompt RAG")
                        k = gr.Slider(2, 10, value=6, step=1, label="k (trechos no contexto)")
                        hibrida = gr.Checkbox(value=True, label="Busca híbrida (vetorial + BM25)")
                        expansao = gr.Checkbox(value=True, label="Expansão de consulta PT/EN")
                        rerank = gr.Checkbox(value=True, label="Reranking por LLM")
            controles = [entrada, chat, sessao, modelo, prompt, k, hibrida, expansao, rerank]
            saidas = [entrada, chat, fontes, trechos, diagnostico]
            entrada.submit(responder, controles, saidas)
            enviar.click(responder, controles, saidas)
            limpar.click(nova_sessao, None, [chat, sessao, fontes, trechos, diagnostico])

        with gr.Tab("Comparar modelos e prompts"):
            gr.Markdown(
                "A mesma pergunta, com o mesmo contexto recuperado, enviada a vários modelos e versões de prompt. "
                f"Provedores configurados: {', '.join(PROVEDORES)}."
            )
            pergunta_cmp = gr.Textbox(label="Pergunta", value=EXEMPLOS[1])
            with gr.Row():
                modelos_cmp = gr.CheckboxGroup(MODELOS, value=MODELOS[:2], label="Modelos")
                prompts_cmp = gr.CheckboxGroup(versoes_disponiveis(), value=["v1", "v4"], label="Prompts")
            botao_cmp = gr.Button("Comparar", variant="primary")
            resumo_cmp = gr.Markdown()
            tabela_cmp = gr.Dataframe(headers=["provedor", "modelo", "prompt", "resposta", "citações", "latência (s)"], wrap=True, interactive=False)
            botao_cmp.click(comparar, [pergunta_cmp, modelos_cmp, prompts_cmp], [tabela_cmp, resumo_cmp])

        with gr.Tab("Base de conhecimento"):
            gr.Markdown("Documentos indexados no ChromaDB persistente (`nomic-embed-text`). Fonte não verificada é mantida para testar a proteção contra injeção via documento.")
            gr.Dataframe(value=tabela_base, headers=["documento", "tipo", "fragmentos", "origem"], wrap=True, interactive=False)
    return demo


def main() -> None:
    demo = construir_interface()
    demo.queue(default_concurrency_limit=2).launch(
        server_name=os.getenv("APP_HOST", "127.0.0.1"),
        server_port=int(os.getenv("APP_PORT", "7860")),
        theme=gr.themes.Soft(),
        css=CSS,
    )


if __name__ == "__main__":
    main()
