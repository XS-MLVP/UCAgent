PYTHON ?= python3
CASE ?= Adder
WORKSPACE ?= output/workspace_$(CASE)
OUTPUT ?= spec
BACKEND ?= langchain
ARGS ?=

PLUGIN_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
REPO_ROOT := $(abspath $(PLUGIN_ROOT)/../..)
UCAGENT := $(if $(wildcard $(REPO_ROOT)/ucagent.py),$(PYTHON) $(REPO_ROOT)/ucagent.py,ucagent)

.DEFAULT_GOAL := help
.PHONY: help validate test package prepare run mcp

help:
	@echo "DEPRECATED: Use SpecGenerator (xiangshan-spec-generator) for document generation."
	@echo "GenSpec: make validate | test | package | prepare | run | mcp"
	@echo "Overrides: CASE=Adder WORKSPACE=output/workspace_Adder OUTPUT=spec BACKEND=langchain ARGS='...'"

validate:
	$(UCAGENT) --validate-plugin "$(PLUGIN_ROOT)"

test:
	PYTHONPATH="$(REPO_ROOT):$(PLUGIN_ROOT)/src:$${PYTHONPATH}" $(PYTHON) -m pytest -q tests

package:
	$(PYTHON) -m build

prepare:
	@test -d "$(PLUGIN_ROOT)/cases/$(CASE)" || { echo "Missing case: $(CASE)" >&2; exit 1; }
	@if test -d "$(WORKSPACE)/$(CASE)"; then \
		echo "Reusing existing inputs: $(WORKSPACE)/$(CASE)"; \
	else \
		mkdir -p "$(WORKSPACE)" && cp -R "$(PLUGIN_ROOT)/cases/$(CASE)" "$(WORKSPACE)/$(CASE)"; \
	fi

run: validate prepare
	$(UCAGENT) "$(WORKSPACE)" "$(CASE)" \
		--plugin "$(PLUGIN_ROOT)" --plugin-workflow gen-spec:generate-spec \
		--output "$(OUTPUT)" --backend "$(BACKEND)" \
		$(if $(filter-out langchain blank,$(BACKEND)),--mcp-server) --tui --loop $(ARGS)

mcp: validate prepare
	$(UCAGENT) "$(WORKSPACE)" "$(CASE)" \
		--plugin "$(PLUGIN_ROOT)" --plugin-workflow gen-spec:generate-spec \
		--output "$(OUTPUT)" --mcp-server --tui $(ARGS)
