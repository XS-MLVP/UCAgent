# =============================
# Docs (MkDocs) local preview
# =============================
.PHONY: docs-help docs-install docs-serve docs-build docs-clean

docs-help:
	@echo "Docs targets:"
	@echo "  make docs-install   # 安装文档构建依赖 (mkdocs/material 等)"
	@echo "  make docs-serve     # 本地预览文档, 默认 127.0.0.1:8000"
	@echo "  make docs-build     # 生成静态站点到 ./site"
	@echo "  make docs-clean     # 清理构建产物 ./site"

docs-install:
	pip3 install -r docs/requirements-docs.txt

docs-serve:
	mkdocs serve -a 127.0.0.1:8030

docs-build:
	mkdocs build

docs-clean:
	rm -rf site


# =============================
# Docs (Pandoc PDF) build
# =============================

DOC := ucagent-doc
VERSION := $(shell git describe --always --dirty --tags 2>/dev/null || git rev-parse --short HEAD)

SRCS := \
	docs/index.md \
	docs/introduce.md \
	docs/usage/direct.md \
	docs/usage/tui.md \
	docs/usage/assit.md \
	docs/usage/mcp.md \
	docs/usage/option.md \
	docs/usage/faq.md \
	docs/tool_list.md \
	docs/customize.md \
	docs/workflow.md

PANDOC_FLAGS += --from=markdown+table_captions+grid_tables+header_attributes+pipe_tables
PANDOC_FLAGS += --table-of-contents --toc-depth=3
PANDOC_FLAGS += --number-sections
PANDOC_FLAGS += --metadata=title:"UCAgent 开发者手册"
PANDOC_FLAGS += --metadata=subtitle:"$(VERSION)"
PANDOC_FLAGS += --resource-path=.:docs:docs/usage
PANDOC_FLAGS += --highlight-style=tango
PANDOC_FLAGS += --filter pandoc-crossref

PANDOC_LATEX_FLAGS += --pdf-engine=xelatex
PANDOC_LATEX_FLAGS += -V documentclass=ctexart
PANDOC_LATEX_FLAGS += -V geometry:margin=2.2cm
PANDOC_LATEX_FLAGS += -V mainfont="Noto Serif CJK SC"
MONO ?= DejaVu Sans Mono
PANDOC_LATEX_FLAGS += -V monofont="$(MONO)"
PANDOC_LATEX_FLAGS += -V fontsize=11pt
PANDOC_LATEX_FLAGS += -H docs/pandoc/header.tex
PANDOC_LATEX_FLAGS += -V fig-pos=H

ifneq ($(TWOSIDE),)
	PANDOC_LATEX_FLAGS += -V twoside
	DOC := $(DOC)-twoside
endif

pdf: $(DOC).pdf

pdf-one:
	@$(MAKE) pdf

pdf-clean:
	rm -f $(DOC)*.pdf $(DOC)*.tex *.aux *.log *.out *.toc *.lof *.lot 2>/dev/null || true

$(DOC).pdf: $(SRCS)
	pandoc $(SRCS) $(PANDOC_FLAGS) $(PANDOC_LATEX_FLAGS) -o $@
	@echo "[INFO] Generated $@"

.PHONY: pdf pdf-one pdf-clean
