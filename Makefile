# =============================
# Docs (MkDocs) local preview
# =============================
.PHONY: docs-help docs-install docs-serve docs-build docs-clean

docs-help:
	@echo "Docs targets:"
	@echo "  make docs-install   # 安装文档构建依赖 (mkdocs/material 等)"
	@echo "  make docs-serve     # 本地预览文档, 默认 127.0.0.1:8030"
	@echo "  make docs-build     # 生成静态站点到 ../site"
	@echo "  make docs-clean     # 清理构建产物 ../site"

docs-install:
	pip3 install -r docs/requirements-docs.txt

docs-serve:
	mkdocs serve -f docs/mkdocs.yml -a 127.0.0.1:8030

docs-build:
	mkdocs build -f docs/mkdocs.yml

docs-clean:
	rm -rf site


# =============================
# Docs (Pandoc PDF) build
# =============================

include docs/pandoc.mk

pdf: $(DOC).pdf

pdf-one:
	@$(MAKE) pdf

pdf-clean:
	rm -f $(DOC)*.pdf $(DOC)*.tex *.aux *.log *.out *.toc *.lof *.lot 2>/dev/null || true

$(DOC).pdf: $(SRCS)
	pandoc $(SRCS) $(PANDOC_FLAGS) $(PANDOC_LATEX_FLAGS) -o $@
	@echo "[INFO] Generated $@"

.PHONY: pdf pdf-one pdf-clean
