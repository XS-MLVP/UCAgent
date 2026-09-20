PLUGIN := src/spec_generator_plugin
export PYTHONPATH := $(CURDIR)/src$(if $(PYTHONPATH),:$(PYTHONPATH))
TEMPLATE := $(PLUGIN)/Guide_Doc/chip_design_document_template_zh.md

.PHONY: repo-lint template-check plugin-check test

repo-lint:
	@for script in $(PLUGIN)/scripts/*.sh; do bash -n "$$script" || exit; done
	python3 -m compileall -q $(PLUGIN) tests
	python3 -m spec_generator_plugin.repository

template-check:
	python3 -m spec_generator_plugin.rendering --document "$(TEMPLATE)" --output-dir .cache/mermaid-check/template

plugin-check:
	ucagent --validate-plugin .

test:
	python3 -m pytest -q
