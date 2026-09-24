PYTHON ?= python3
PLUGIN_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UCAgent_ROOT := $(abspath $(PLUGIN_ROOT)/../..)
UCAgent_PYTHONPATH := $(PLUGIN_ROOT):$(UCAgent_ROOT)
UCAGENT := $(PYTHON) $(UCAgent_ROOT)/ucagent.py
INPUT_ROOT ?= $(UCAgent_ROOT)/examples
OUTPUT_ROOT ?= $(UCAgent_ROOT)/output/bug_review
CONFIG ?= $(PLUGIN_ROOT)/bug_review.toml
AGENT_ARGS ?= --backend blank --mcp-server --human --tui
ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help plugin-check bug-review-analysis bug-review-scoring

help:
	@echo "make bug_review_<name>       review $(INPUT_ROOT)/workspace_<name>"
	@echo "make bug-review-scoring ANALYSIS_NAME=<name>"
	@echo "make plugin-check           validate the bug_review plugin"
	@echo "Workspaces: $(OUTPUT_ROOT)/workspace_<name>"

plugin-check:
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(UCAGENT) --validate-plugin "$(PLUGIN_ROOT)"

bug_review_%:
	@$(MAKE) --no-print-directory bug-review-analysis INPUT_NAME="$*"

bug-review-analysis:
	@test -n "$(INPUT_NAME)" || { echo "Set INPUT_NAME=<name>" >&2; exit 2; }
	@test -d "$(INPUT_ROOT)/workspace_$(INPUT_NAME)" || { echo "Missing input workspace: $(INPUT_ROOT)/workspace_$(INPUT_NAME)" >&2; exit 1; }
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(PYTHON) -m bug_review.input_preparation \
		--source "$(INPUT_ROOT)/workspace_$(INPUT_NAME)" \
		--destination "$(OUTPUT_ROOT)/workspace_$(INPUT_NAME)/input_runs" --run-tests
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(PYTHON) -m bug_review.workflow prepare-analysis \
		--config "$(CONFIG)" --workspace "$(OUTPUT_ROOT)/workspace_$(INPUT_NAME)" \
		--run "workspace_$(INPUT_NAME)=$(OUTPUT_ROOT)/workspace_$(INPUT_NAME)/input_runs" --replay-enabled true
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(UCAGENT) "$(OUTPUT_ROOT)/workspace_$(INPUT_NAME)" BugReview \
		--plugin "$(PLUGIN_ROOT)" --plugin-workflow bug_review:analysis $(AGENT_ARGS) $(ARGS)

bug-review-scoring:
	@test -n "$(ANALYSIS_NAME)" || { echo "Set ANALYSIS_NAME=<name>" >&2; exit 2; }
	@test -f "$(OUTPUT_ROOT)/workspace_$(ANALYSIS_NAME)/analysis/analysis_manifest.json" || { echo "Missing analysis manifest" >&2; exit 1; }
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(PYTHON) -m bug_review.workflow prepare-scoring \
		--analysis-manifest "$(OUTPUT_ROOT)/workspace_$(ANALYSIS_NAME)/analysis/analysis_manifest.json" \
		--workspace "$(OUTPUT_ROOT)/workspace_$(ANALYSIS_NAME)-scoring"
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(UCAGENT) "$(OUTPUT_ROOT)/workspace_$(ANALYSIS_NAME)-scoring" BugReview \
		--plugin "$(PLUGIN_ROOT)" --plugin-workflow bug_review:scoring $(AGENT_ARGS) $(ARGS)
