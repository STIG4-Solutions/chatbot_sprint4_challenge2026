import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
# Os testes unitários não fazem chamada de rede: a chave só precisa existir
# para que `carregar_configuracao()` não interrompa a importação. Nos testes
# de integração a chave real vem do `.env`, que o `load_dotenv` não
# sobrescreveria se uma chave fictícia já estivesse no ambiente.
if not os.getenv("RODAR_INTEGRACAO"):
    os.environ.setdefault("OLLAMA_API_KEY", "chave-de-teste")


def pytest_configure(config):
    config.addinivalue_line("markers", "integracao: exige Ollama local, ChromaDB indexado e Ollama Cloud")


def pytest_collection_modifyitems(config, items):
    if os.getenv("RODAR_INTEGRACAO"):
        return
    pular = pytest.mark.skip(reason="defina RODAR_INTEGRACAO=1 para rodar os testes de integração")
    for item in items:
        if "integracao" in item.keywords:
            item.add_marker(pular)
