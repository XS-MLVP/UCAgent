PYTHON ?= python3
PLUGIN_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UCAgent_ROOT := $(abspath $(PLUGIN_ROOT)/../..)
UCAgent_PYTHONPATH := $(PLUGIN_ROOT)/src:$(UCAgent_ROOT)
UCAGENT := $(PYTHON) $(UCAgent_ROOT)/ucagent.py
INPUT_ROOT ?= $(PLUGIN_ROOT)/inputs
OUTPUT_ROOT ?= $(PLUGIN_ROOT)/output
AGENT_ARGS ?= --backend blank --mcp-server --human --tui
ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help plugin-check bug-review-analysis

help:
	@echo "make bug-review-analysis     review all $(INPUT_ROOT)/workspace_*"
	@echo "make bug_review_<name>       review $(INPUT_ROOT)/workspace_<name>"
	@echo "make plugin-check           validate the bug_review plugin"
	@echo "Prepared inputs: $(OUTPUT_ROOT)/results/tests/workspace_*"
	@echo "Report: $(OUTPUT_ROOT)/results/index.html"

plugin-check:
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(UCAGENT) --validate-plugin "$(PLUGIN_ROOT)"

bug_review_%:
	@$(MAKE) --no-print-directory bug-review-analysis INPUT_NAME="$*"

bug-review-analysis:
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(PYTHON) -m bug_review.workflow prepare-analysis \
		--input-root "$(INPUT_ROOT)" --output-root "$(OUTPUT_ROOT)" $(if $(INPUT_NAME),--run "workspace_$(INPUT_NAME)=$(INPUT_ROOT)/workspace_$(INPUT_NAME)")
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(UCAGENT) "$(OUTPUT_ROOT)" BugReview \
		--plugin "$(PLUGIN_ROOT)" --plugin-workflow bug_review:analysis --output results $(AGENT_ARGS) $(ARGS)
