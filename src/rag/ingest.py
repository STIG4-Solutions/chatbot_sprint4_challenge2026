"""
Ingestão da base de conhecimento no ChromaDB persistente.

Uso:
    python -m src.rag.ingest                       # configuração padrão
    python -m src.rag.ingest --reindexar           # força a reconstrução
    python -m src.rag.ingest --chunk 1000 --overlap 150 --sem-prefixo
"""

from __future__ import annotations

import argparse
import time
from collections import Counter

from src.config import carregar_configuracao
from src.rag.chunking import EstrategiaChunking
from src.rag.vector_store import ConfiguracaoIndice, abrir_indice, todos_os_fragmentos


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__)
    argumentos.add_argument("--chunk", type=int, default=500)
    argumentos.add_argument("--overlap", type=int, default=50)
    argumentos.add_argument("--sem-prefixo", action="store_true")
    argumentos.add_argument("--sem-sanitizacao", action="store_true")
    argumentos.add_argument("--reindexar", action="store_true")
    opcoes = argumentos.parse_args()

    configuracao = carregar_configuracao()
    indice = ConfiguracaoIndice(
        EstrategiaChunking(opcoes.chunk, opcoes.overlap),
        com_prefixo=not opcoes.sem_prefixo,
        sanitizar=not opcoes.sem_sanitizacao,
    )
    inicio = time.perf_counter()
    loja = abrir_indice(indice, configuracao, reindexar=opcoes.reindexar, verbose=True)
    fragmentos = todos_os_fragmentos(loja)
    por_arquivo = Counter(f.metadata["arquivo"] for f in fragmentos)
    suspeitos = [f for f in fragmentos if f.metadata.get("suspeito_injecao")]

    print(f"\ncoleção: {loja._collection.name} em {configuracao.diretorio_chroma}")
    print(f"embeddings: {configuracao.modelo_embeddings} @ {configuracao.embeddings_base_url}")
    print(f"estratégia: {indice.estrategia.rotulo} · prefixo={indice.com_prefixo} · sanitização={indice.sanitizar}")
    print(f"fragmentos: {len(fragmentos)} · tempo: {time.perf_counter() - inicio:.1f} s")
    for arquivo, total in sorted(por_arquivo.items()):
        print(f"  {total:5d}  {arquivo}")
    print(f"fragmentos marcados como suspeitos de injeção: {len(suspeitos)}")
    for f in suspeitos:
        print(f"  - {f.metadata['arquivo']} p.{f.metadata['pagina']}: {f.metadata['motivos_injecao']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
