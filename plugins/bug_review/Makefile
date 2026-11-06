PLUGIN_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UCAgent_ROOT := $(abspath $(PLUGIN_ROOT)/../..)
PYTHON ?= python3
PYTHONPATH_REVIEW := $(PLUGIN_ROOT)/src:$(UCAgent_ROOT)
UCAGENT := $(PYTHON) $(UCAgent_ROOT)/ucagent.py
INPUT_ROOT ?= $(PLUGIN_ROOT)/inputs
OUTPUT_ROOT ?= $(PLUGIN_ROOT)/output
OUT ?= results
REVIEW_ARGS ?= --backend claude --mcp-server --mcp-server-port -1 --loop --exit-on-completion
MCP_REVIEW_ARGS ?= -s -hm --tui --mcp-server-no-file-tools
ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help plugin-check serve bug_review_all
help:
	@echo "init_<module>: prepare a fresh workspace; source inputs are never compiled or edited"
	@echo "bug_review_<module> / mcp_bug_review_<module>: run targeted Bug review"
	@echo "Use a new OUTPUT_ROOT for every run. OUT=results by default."
	@echo "BUG_REVIEW_WAVEFORM_ENABLED=true enables the optional stage."

plugin-check:
	PYTHONPATH="$(PYTHONPATH_REVIEW)" $(UCAGENT) --validate-plugin "$(PLUGIN_ROOT)"

init_%:
	PYTHONPATH="$(PYTHONPATH_REVIEW)" $(PYTHON) -m bug_review.workspace --source "$(INPUT_ROOT)/$*" --workspace "$(OUTPUT_ROOT)/$*"

# A prepared but not started workspace can be launched once. Repeated runs use a new OUTPUT_ROOT.
define launch
@test ! -f "$(OUTPUT_ROOT)/$*/$(OUT)/review.json" || { echo "review already started; use a new OUTPUT_ROOT"; exit 1; }
@if [ ! -d "$(OUTPUT_ROOT)/$*" ]; then $(MAKE) --no-print-directory init_$*; fi
PYTHONPATH="$(PYTHONPATH_REVIEW)" $(UCAGENT) "$(OUTPUT_ROOT)/$*" "$(if $(DUT),$(DUT),$*)" --plugin "$(PLUGIN_ROOT)" --plugin-workflow bug_review:analysis --output "$(OUT)" $(1) $(ARGS)
endef

bug_review_%:
	$(call launch,$(REVIEW_ARGS))
mcp_bug_review_%:
	$(call launch,$(MCP_REVIEW_ARGS))
bug_review_all:
	@for dir in "$(INPUT_ROOT)"/*/; do $(MAKE) --no-print-directory bug_review_$$(basename "$$dir") || exit 1; done
publish_%:
	PYTHONPATH="$(PYTHONPATH_REVIEW)" $(PYTHON) -c 'from bug_review.publishing import publish_run; print(publish_run("$(OUTPUT_ROOT)/$*", "$(OUTPUT_ROOT)"))'
serve:
	PYTHONPATH="$(PYTHONPATH_REVIEW)" $(PYTHON) -m bug_review.report_server --output-root "$(OUTPUT_ROOT)"
