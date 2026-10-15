PLUGIN_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UCAgent_ROOT := $(abspath $(PLUGIN_ROOT)/../..)
PYTHON ?= $(if $(wildcard $(UCAgent_ROOT)/.venv/bin/python3),$(UCAgent_ROOT)/.venv/bin/python3,python3)
PYTHON_BIN := $(abspath $(PYTHON))
# picker's internal build must target the same Python that runs the review.
ifneq (,$(findstring /bin/,$(PYTHON_BIN)))
PICKER_ENV := PATH="$(dir $(PYTHON_BIN)):$$PATH" VIRTUAL_ENV="$(patsubst %/bin/,%,$(dir $(PYTHON_BIN)))"
else
PICKER_ENV :=
endif
UCAgent_PYTHONPATH := $(PLUGIN_ROOT)/src:$(UCAgent_ROOT)
UCAGENT := $(PYTHON) $(UCAgent_ROOT)/ucagent.py
INPUT_ROOT ?= $(PLUGIN_ROOT)/inputs
OUTPUT_ROOT ?= $(PLUGIN_ROOT)/output
# Extra picker export flags for the example DUT (--no-timing avoids the
# C++20 coroutine requirement verilated timing support would add).
PICKER_ARGS ?= --vflag=--no-timing

# Agent launch modes, mirroring the root Makefile's mcp_% / test_% split:
# unattended full review, or an interactive TUI session.
REVIEW_ARGS ?= --backend claude --mcp-server --mcp-server-port -1 --loop --exit-on-completion
MCP_REVIEW_ARGS ?= -s -hm --tui --mcp-server-no-file-tools
ARGS ?=

# Run one prepared module workspace with the selected UCAgent arguments.
define launch_review
PATH="$(dir $(PYTHON_BIN)):$$PATH" PYTHONPATH="$(UCAgent_PYTHONPATH)" $(UCAGENT) "$(OUTPUT_ROOT)/$*" BugReview \
	--plugin "$(PLUGIN_ROOT)" --plugin-workflow bug_review:analysis --output verification_review/analysis $(1) $(ARGS)
endef

.DEFAULT_GOAL := help
.PHONY: help plugin-check bug_review_all serve

help:
	@echo "Bug Review plugin (inputs/<module>/ -> output/<module>/)"
	@echo "  make bug_review_<module>     launch unattended; prepare only if the workspace is absent"
	@echo "  make mcp_bug_review_<module> launch TUI and MCP; resume an existing workspace"
	@echo "  make bug_review_all          review every inputs/<module>/ in turn"
	@echo "  make init_<module>           prepare files: build the picker DUT package (if missing) and a module workspace"
	@echo "  make status_<module>         print stage status of the module workspace"
	@echo "  make publish_<module>        publish the module workspace and rebuild the portal"
	@echo "  make serve                   serve published reports on localhost"
	@echo "  make plugin-check            validate the plugin"
	@echo "Variables: INPUT_ROOT=$(INPUT_ROOT) OUTPUT_ROOT=$(OUTPUT_ROOT)"

plugin-check:
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(UCAGENT) --validate-plugin "$(PLUGIN_ROOT)"

# Input preparation, like the root Makefile's init_%: validate the module
# exists, compile the DUT package once (build-if-missing), then prepare a
# fresh run workspace for it.
init_%:
	@case "$*" in ''|[0-9]*|*[!A-Za-z0-9_]*) echo "invalid Python module name: $*"; exit 1;; esac
	@test -d "$(INPUT_ROOT)/$*" || { echo "missing input module: $(INPUT_ROOT)/$*"; exit 1; }
	@test ! -e "$(OUTPUT_ROOT)/$*" || { echo "output already exists: $(OUTPUT_ROOT)/$*"; exit 1; }
	@test -d "$(INPUT_ROOT)/$*/unity_test/tests" || { echo "missing tests: $(INPUT_ROOT)/$*/unity_test/tests"; exit 1; }
	@test -f "$(INPUT_ROOT)/$*/launch.yaml" || { echo "missing launch.yaml: $(INPUT_ROOT)/$*"; exit 1; }
	@test -f "$(INPUT_ROOT)/$*/filelist.f" -o -f "$(INPUT_ROOT)/$*/filelist.txt" || { echo "missing filelist: $(INPUT_ROOT)/$*"; exit 1; }
	@test -f "$(INPUT_ROOT)/$*/unity_test/$*_bug_summary.md" -o -f "$(INPUT_ROOT)/$*/unity_test/$*_bug_analysis.md" || { echo "missing original Bug report: $(INPUT_ROOT)/$*/unity_test"; exit 1; }
	@filelist="$(INPUT_ROOT)/$*/filelist.f"; [ -f "$$filelist" ] || filelist="$(INPUT_ROOT)/$*/filelist.txt"; found=0; \
		while IFS= read -r item || [ -n "$$item" ]; do \
			case "$$item" in ''|'#'*|'+'*) continue;; esac; \
			case "$$item" in /*) path="$$item";; *) path="$(INPUT_ROOT)/$*/$$item";; esac; \
			[ -f "$$path" ] || { echo "inaccessible RTL: $$item"; exit 1; }; \
			found=1; \
		done < "$$filelist"; \
		[ "$$found" -eq 1 ] || { echo "filelist has no RTL sources: $$filelist"; exit 1; }
	@if [ ! -d "$(INPUT_ROOT)/$*/$*" ]; then \
		echo "DUT package missing, compiling via picker..."; \
		filelist="$(INPUT_ROOT)/$*/filelist.f"; [ -f "$$filelist" ] || filelist="$(INPUT_ROOT)/$*/filelist.txt"; \
		$(PICKER_ENV) picker export --rw 1 --sname "$*" --tdir "$(INPUT_ROOT)/$*/" \
			-c -w "$(INPUT_ROOT)/$*/$*/$*.fst" \
			--filelist "$$filelist" $(PICKER_ARGS) || exit 1; \
	fi
	@test -f "$(INPUT_ROOT)/$*/$*/__init__.py" || { echo "missing compiled DUT package: $(INPUT_ROOT)/$*/$*"; exit 1; }
	@PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(INPUT_ROOT)/$*:$(UCAgent_PYTHONPATH)" $(PYTHON) -c 'import $*' || { echo "DUT package cannot import; supply a complete package for this Python/ABI or rebuild in a separate staging directory. Input files were preserved."; exit 1; }
	@mkdir -p "$(OUTPUT_ROOT)/$*/verification_review/run/unity_test" "$(OUTPUT_ROOT)/$*/verification_review/run/test_report" "$(OUTPUT_ROOT)/$*/verification_review/analysis" "$(OUTPUT_ROOT)/$*/verification_review/report" "$(OUTPUT_ROOT)/$*/verification_review/notes"
	@rsync -a --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude 'toffee_tmp_*/' \
		"$(INPUT_ROOT)/$*/unity_test/" "$(OUTPUT_ROOT)/$*/verification_review/run/unity_test/"
	@rsync -a --exclude 'unity_test/' --exclude 'launch.yaml' --exclude 'filelist.f' --exclude 'filelist.txt' --exclude 'toffee_tmp_*/' \
		--exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.ucagent/' \
		--exclude '.git/' --exclude '.venv/' --exclude 'venv/' --exclude 'build/' \
		--exclude 'dist/' --exclude 'node_modules/' --exclude 'output/' \
		--exclude 'results/' --exclude 'uc_test_report/' --exclude '*.fst' --exclude '*.vcd' \
		"$(INPUT_ROOT)/$*/" "$(OUTPUT_ROOT)/$*/"
	@PYTHONPATH="$(OUTPUT_ROOT)/$*:$(OUTPUT_ROOT)/$*/verification_review/run/unity_test:$(UCAgent_PYTHONPATH)" $(PYTHON) -c 'import $*'
	@find "$(OUTPUT_ROOT)/$*/verification_review/run/unity_test" -type f -exec chmod a-w {} +

bug_review_%:
	@if [ ! -e "$(OUTPUT_ROOT)/$*" ]; then $(MAKE) --no-print-directory -f "$(PLUGIN_ROOT)/Makefile" init_$*; fi
	@test -d "$(OUTPUT_ROOT)/$*/verification_review/analysis" -a -d "$(OUTPUT_ROOT)/$*/verification_review/run/unity_test" -a -d "$(OUTPUT_ROOT)/$*/verification_review/run/test_report" || { echo "incomplete module workspace: $(OUTPUT_ROOT)/$*"; exit 1; }
	@$(call launch_review,$(REVIEW_ARGS))

mcp_bug_review_%:
	@if [ ! -e "$(OUTPUT_ROOT)/$*" ]; then $(MAKE) --no-print-directory -f "$(PLUGIN_ROOT)/Makefile" init_$*; fi
	@test -d "$(OUTPUT_ROOT)/$*/verification_review/analysis" -a -d "$(OUTPUT_ROOT)/$*/verification_review/run/unity_test" -a -d "$(OUTPUT_ROOT)/$*/verification_review/run/test_report" || { echo "incomplete module workspace: $(OUTPUT_ROOT)/$*"; exit 1; }
	@$(call launch_review,$(MCP_REVIEW_ARGS))

bug_review_all:
	@for dir in $(INPUT_ROOT)/*/; do \
		name=$$(basename "$$dir"); \
		case "$$name" in .*|third-party) continue;; esac; \
		$(MAKE) --no-print-directory bug_review_$$name || exit 1; \
	done

status_%:
	@PYTHONPATH="$(UCAgent_PYTHONPATH)" $(PYTHON) -c 'import json; from bug_review.checkers.analysis import Workflow; print(json.dumps(Workflow("$(OUTPUT_ROOT)/$*").status(), indent=2))'

publish_%:
	@PYTHONPATH="$(UCAgent_PYTHONPATH)" $(PYTHON) -c 'from bug_review.publishing import publish_run; print(publish_run("$(OUTPUT_ROOT)/$*", "$(OUTPUT_ROOT)"))'

serve:
	PYTHONPATH="$(UCAgent_PYTHONPATH)" $(PYTHON) -m bug_review.report_server --output-root "$(OUTPUT_ROOT)"
