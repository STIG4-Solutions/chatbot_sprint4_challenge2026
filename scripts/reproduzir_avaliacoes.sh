#!/usr/bin/env bash
# Reproduz todas as medições da Sprint 4 (cerca de 1h30 com o tier gratuito da
# Ollama Cloud). Pré-requisitos: .env preenchido, `ollama serve` rodando e
# `ollama pull nomic-embed-text`. Resultados em evals/resultados/.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}

# 1. Recuperação isolada: chunking, prefixo, busca híbrida, expansão e rerank
$PY -m evals.benchmark_recuperacao

# 2. Antes: Sprints 1/2 e Sprint 3 no mesmo eval set
$PY -m evals.run_rag_eval --preset sprint2
$PY -m evals.run_rag_eval --preset sprint3

# 3. Iterações do RAG (prompts/rag/VERSIONS.md)
$PY -m evals.run_rag_eval --preset it1
$PY -m evals.run_rag_eval --preset it2
$PY -m evals.run_rag_eval --preset it3

# 4. Modelos e parâmetros (docs/relatorio_modelos.md), sobre a configuração it3
$PY -m evals.run_rag_eval --preset it3 --modelo gemma4:31b --nome modelo_gemma4_31b
$PY -m evals.run_rag_eval --preset it3 --modelo gpt-oss:20b --nome modelo_gpt_oss_20b
$PY -m evals.run_rag_eval --preset it3 --temperature 0.7 --nome param_temperature_0_7
$PY -m evals.run_rag_eval --preset it3 --k 3 --nome param_k3
$PY -m evals.run_rag_eval --preset it3 --k 10 --nome param_k10
$PY -m evals.run_rag_eval --preset it3 --max-tokens 250 --sem-ragas --nome param_max_tokens_250

# 5. Bônus: multi-provider, modelos x prompts com o mesmo contexto
$PY -m evals.comparar_multiprovider

$PY -m evals.consolidar
