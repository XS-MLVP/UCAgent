# =============================
# Pandoc PDF build config
# =============================

DOC := ucagent-doc
VERSION := $(shell git describe --always --dirty --tags 2>/dev/null || git rev-parse --short HEAD)

SRCS := \
	docs/index.md \
	docs/introduce.md \
	docs/usage/mcp.md \
	docs/usage/direct.md \
	docs/usage/assit.md \
	docs/usage/option.md \
	docs/usage/tui.md \
	docs/usage/faq.md \
	docs/workflow.md \
	docs/customize.md \
	docs/workflow.md

# -------- Pandoc general parameters --------
PANDOC_FLAGS += --from=markdown+table_captions+grid_tables+header_attributes+pipe_tables
PANDOC_FLAGS += --table-of-contents --toc-depth=3
PANDOC_FLAGS += --number-sections
PANDOC_FLAGS += --metadata=title:"UCAgent 开发者手册"
PANDOC_FLAGS += --metadata=subtitle:"$(VERSION)"
PANDOC_FLAGS += --resource-path=.:docs:docs/usage
PANDOC_FLAGS += --highlight-style=tango
PANDOC_FLAGS += --filter pandoc-crossref

# -------- LaTeX / PDF parameters --------
PANDOC_LATEX_FLAGS += --pdf-engine=xelatex
PANDOC_LATEX_FLAGS += -V documentclass=ctexart
PANDOC_LATEX_FLAGS += -V geometry:margin=2.2cm
PANDOC_LATEX_FLAGS += -V mainfont="Noto Serif CJK SC"

MONO ?= DejaVu Sans Mono
PANDOC_LATEX_FLAGS += -V monofont="$(MONO)"
PANDOC_LATEX_FLAGS += -V fontsize=11pt
PANDOC_LATEX_FLAGS += -H docs/pandoc/header.tex
PANDOC_LATEX_FLAGS += -V fig-pos=H

# -------- Twoside print (optional) --------
ifneq ($(TWOSIDE),)
	PANDOC_LATEX_FLAGS += -V twoside
	DOC := $(DOC)-twoside
endif
