"""
Gera `docs/relatorio_evolucao.pdf` a partir do markdown fonte.

O relatório é escrito em markdown para permanecer versionado e comparável em
diff; o PDF é o artefato de entrega exigido pelo escopo da sprint.
"""

from __future__ import annotations

from pathlib import Path

from markdown_pdf import MarkdownPdf, Section

DIRETORIO = Path(__file__).resolve().parent
FONTE = DIRETORIO / "relatorio_evolucao.md"
DESTINO = DIRETORIO / "relatorio_evolucao.pdf"

# Folha de estilo deliberadamente sóbria: texto preto sobre fundo branco, sem
# preenchimento de célula, sem cor de destaque e sem elemento decorativo. O
# documento é um relatório técnico de avaliação, e a legibilidade em impressão
# monocromática vale mais do que qualquer refinamento visual.
#
# Sobre a fonte: o renderizador aplica ligaduras tipográficas ("fi", "fl", "ff"
# viram um único caractere Unicode), o que deixa algumas palavras fora da busca
# por palavra isolada no leitor de PDF. Substituir a fonte por uma do sistema
# remove as ligaduras, mas converte todos os espaços em espaço não separável, o
# que quebra a busca por frase em todo o texto. Mantém-se a fonte padrão, e o
# markdown fonte fica versionado ao lado do PDF, integralmente pesquisável.
CSS = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.40;
       color: #000000; background: #ffffff; }
h1 { font-size: 16pt; margin: 0 0 4pt 0; color: #000000; }
h2 { font-size: 12pt; margin: 14pt 0 5pt 0; color: #000000; }
h3 { font-size: 10.5pt; margin: 10pt 0 3pt 0; color: #000000; }
p  { margin: 5pt 0; text-align: justify; color: #000000; }
table { border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 7pt 0; }
th { text-align: left; font-weight: bold; }
th, td { border: 0.6pt solid #000000; padding: 3pt 5pt; vertical-align: top; color: #000000; }
code { font-family: Menlo, Consolas, monospace; font-size: 9pt; color: #000000; }
li { margin: 2pt 0; }
hr { border: 0; border-top: 0.6pt solid #000000; margin: 10pt 0; }
"""


def main() -> int:
    pdf = MarkdownPdf(toc_level=0, optimize=True)
    pdf.add_section(Section(FONTE.read_text(encoding="utf-8"), paper_size="A4"), user_css=CSS)
    pdf.meta["title"] = "Relatório de evolução do projeto · ChargeGrid Intelligence Sprint 4"
    pdf.meta["author"] = "Grupo 2 · Turma 1CCR · FIAP"
    pdf.save(DESTINO)
    print(f"gerado: {DESTINO.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
