PLUGIN := src/rtl2spec
export PYTHONPATH := $(CURDIR)/src$(if $(PYTHONPATH),:$(PYTHONPATH))
TEMPLATE := $(PLUGIN)/Guide_Doc/chip_design_document_template_zh.md

.PHONY: repo-lint template-check plugin-check test

repo-lint:
	@for script in $(PLUGIN)/scripts/*.sh; do bash -n "$$script" || exit; done
	python3 -m compileall -q $(PLUGIN) tests
	python3 -m rtl2spec.repository

template-check:
	python3 -c 'from pathlib import Path; from rtl2spec.documents import markdown_tokens; markdown_tokens(Path("$(TEMPLATE)").read_text(encoding="utf-8"))'

plugin-check:
	ucagent --validate-plugin .

test:
	python3 -m pytest -q
