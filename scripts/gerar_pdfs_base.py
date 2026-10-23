"""
Gera os PDFs dos documentos do projeto a partir das fontes em markdown.

Os documentos autorais da base (manual de operação, política tarifária, FAQ,
regimento condominial de contraste e o documento de teste de injeção) são
mantidos em `data/knowledge_base/fontes_autorais/*.md`, versionados e
comparáveis em diff. O pipeline RAG lê apenas PDF (`PyMuPDFLoader`), por isso
cada fonte é convertida em um PDF com sumário (bookmarks), que o loader usa
para atribuir a seção de cada fragmento.

Uso: python -m scripts.gerar_pdfs_base
"""

from __future__ import annotations

from pathlib import Path

from markdown_pdf import MarkdownPdf, Section

RAIZ = Path(__file__).resolve().parent.parent
FONTES = RAIZ / "data" / "knowledge_base" / "fontes_autorais"
DESTINO = RAIZ / "data" / "knowledge_base"

CSS = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.4; }
h1 { font-size: 16pt; } h2 { font-size: 13pt; margin-top: 14pt; } h3 { font-size: 11pt; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; }
th, td { border: 0.6pt solid #000; padding: 3pt 5pt; text-align: left; vertical-align: top; }
"""


def main() -> int:
    for fonte in sorted(FONTES.glob("*.md")):
        texto = fonte.read_text(encoding="utf-8")
        titulo = texto.splitlines()[0].lstrip("# ").strip()
        pdf = MarkdownPdf(toc_level=3, optimize=True)
        pdf.add_section(Section(texto, paper_size="A4"), user_css=CSS)
        pdf.meta["title"] = titulo
        pdf.meta["author"] = "Grupo 2 · Turma 1CCR · FIAP"
        destino = DESTINO / f"{fonte.stem}.pdf"
        pdf.save(destino)
        print(f"gerado: {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
