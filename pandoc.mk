# =============================
# Pandoc PDF build config
# =============================

DOC := ucagent-doc
VERSION := $(shell git describe --always --dirty --tags 2>/dev/null || git rev-parse --short HEAD)

# Auto-generate SRCS by sorting filenames (by basename) with numeric prefixes
SRCS := $(shell find docs/content -type f -name "*.md" -printf "%p\n" | sort)

# Auto-generate resource paths from directories containing images
RESOURCE_DIRS := $(shell find docs/content -type f \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" -o -name "*.svg" \) -printf "%h\n" | sort -u | tr '\n' ':' | sed 's/:$$//')
RESOURCE_PATH := .:docs:docs/content:$(RESOURCE_DIRS)

# -------- Pandoc general parameters --------
PANDOC_FLAGS += --from=markdown+table_captions+grid_tables+header_attributes+pipe_tables
PANDOC_FLAGS += --table-of-contents --toc-depth=3
PANDOC_FLAGS += --number-sections
PANDOC_FLAGS += --metadata=title:"UCAgent 开发者手册"
PANDOC_FLAGS += --metadata=subtitle:"$(VERSION)"
# Search paths for images/resources after content relocation
PANDOC_FLAGS += --resource-path=$(RESOURCE_PATH)
PANDOC_FLAGS += --highlight-style=tango
PANDOC_FLAGS += --filter pandoc-crossref
PANDOC_FLAGS += --lua-filter=docs/pandoc/convert_md_links.lua
PANDOC_FLAGS += --lua-filter=docs/pandoc/auto_colwidth.lua

# -------- LaTeX / PDF parameters --------
# 允许通过环境变量覆盖 PDF 引擎，默认使用 xelatex；
# 在 CI 中可设置 PDF_ENGINE=tectonic 以自动拉取依赖包，避免缺包。
PDF_ENGINE ?= xelatex
PANDOC_LATEX_FLAGS += --pdf-engine=$(PDF_ENGINE)
PANDOC_LATEX_FLAGS += -V documentclass=ctexart
PANDOC_LATEX_FLAGS += -V geometry:margin=2.2cm
PANDOC_LATEX_FLAGS += -V mainfont="Noto Serif CJK SC"
PANDOC_LATEX_FLAGS += -V colorlinks=true
PANDOC_LATEX_FLAGS += -V linkcolor=blue
PANDOC_LATEX_FLAGS += -V urlcolor=cyan
PANDOC_LATEX_FLAGS += -V citecolor=green

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
