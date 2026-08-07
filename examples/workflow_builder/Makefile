.PHONY: help configure configure-check configure-show prepare_input prepare_workspace_state prepare_inc_workspace run run_cli run_inc run_inc_cli \
	run_eval run_eval_cli run_eval_tools run_eval_tools_cli run_eval_checkers run_eval_checkers_cli \
	run_eval_flow run_eval_flow_cli run_eval_env run_eval_env_cli \
	run_eval_runtime_default run_eval_runtime_default_cli run_eval_runtime_inc run_eval_runtime_inc_cli \
	aggregate_eval \
	eval-review eval-list eval-approve eval-reject eval-defer eval-suggest \
	eval-ui session session_cli session_inc session_eval regression clean
.NOTPARALLEL: run_eval

WORKFLOW_BUILDER_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
LOCAL_CONFIG ?= $(WORKFLOW_BUILDER_DIR)/.workflow_builder/local.mk
-include $(LOCAL_CONFIG)

UCAGENT_HOME ?= $(HOME)/FDocB/UCAgent
WORKFLOW_BUILDER_HOME ?= $(UCAGENT_HOME)/examples/workflow_builder

UCAGENT_VENV ?= $(UCAGENT_HOME)/.venv

WS ?= $(WORKFLOW_BUILDER_HOME)/workspace

TARGET ?= workflow
SESSION ?= ucagent_workflow_builder
INC_SESSION ?= ucagent_workflow_builder_inc
EVAL_SESSION ?= ucagent_workflow_builder_eval
OUT ?= .
NORMALIZED_OUT := $(patsubst %/,%,$(OUT))
# Keep each isolated workspace paired with its sibling input directory:
#   <workspace-root>/input + <workspace-root>/workspace
INPUT_DIR ?= $(abspath $(WS)/../input)
GUIDE_FILE ?= $(INPUT_DIR)/guide.md
WFGEN_SOURCE_DIR ?= $(WORKFLOW_BUILDER_HOME)/wfgen
GUIDE_DOC_SOURCE_DIR ?= $(WORKFLOW_BUILDER_HOME)/Guide_Doc
RUN_EXTRA ?=
ID ?=
REASON ?=
TITLE ?=
DESCRIPTION ?=
PRIORITY ?= medium
RUN_LOOP_MSG ?= Continue the workflow_builder workflow through all stages. Build and statically validate the generated workflow candidate. Do not run generated default or incremental workflows inside the main flow.
RUN_LOOP_ARGS ?= --loop --loop-msg "$(RUN_LOOP_MSG)"
HISTORY_GUARD_INTERVAL ?= 0.2
INC_LOOP_MSG ?= Apply only explicitly approved eval findings or user suggestions. Keep candidates in tmp, run affected deterministic checks, and leave fixes pending re-evaluation.
EVAL_LOOP_MSG ?= Evaluate only the selected responsibility, preserve report history through StructuredJsonStore, and never modify the generated workflow.
MCP_SERVER_HOST ?= 127.0.0.1
MCP_SERVER_PORT ?= 5000
EVAL_UI_HOST ?= 127.0.0.1
EVAL_UI_PORT ?= 8765

PYTHON ?= $(UCAGENT_VENV)/bin/python

WFB_WORKSPACE ?= $(WS)
WORKSPACE_INPUT_DIR ?= $(WFB_WORKSPACE)/input
WORKSPACE_WFGEN_DIR ?= $(WFB_WORKSPACE)/wfgen
WORKSPACE_GUIDE_DOC_DIR ?= $(WFB_WORKSPACE)/Guide_Doc
CONFIG_FILE ?= $(WORKFLOW_BUILDER_HOME)/config.yaml
INC_CONFIG_FILE ?= $(WORKFLOW_BUILDER_HOME)/inc.yaml
EVAL_TOOLS_CONFIG_FILE ?= $(WORKFLOW_BUILDER_HOME)/eval_tools.yaml
EVAL_CHECKERS_CONFIG_FILE ?= $(WORKFLOW_BUILDER_HOME)/eval_checkers.yaml
EVAL_FLOW_CONFIG_FILE ?= $(WORKFLOW_BUILDER_HOME)/eval_flow.yaml
EVAL_ENV_CONFIG_FILE ?= $(WORKFLOW_BUILDER_HOME)/eval_env.yaml
EVAL_RUN_CONFIG_FILE ?= $(WORKFLOW_BUILDER_HOME)/eval_run.yaml
EVAL_OUTPUT_ROOT ?= tmp/eval_agent_outputs
EVAL_LOG_DIR ?= tmp/eval_logs
GUIDE_DOC_PATH ?= $(WORKFLOW_BUILDER_HOME)/Guide_Doc/
WORKFLOW_PYTHONPATH := $(UCAGENT_HOME):$${PYTHONPATH:-}
UCAGENT := $(PYTHON) $(UCAGENT_HOME)/ucagent.py

help:
	@echo "Workflow Builder direct workflow"
	@echo "  make configure     - Interactively configure machine-local defaults"
	@echo "  make configure-check - Validate the saved machine-local environment"
	@echo "  make configure-show  - Show the effective machine-local environment"
	@echo "  make run           - Start the 24-stage main workflow in supervised auto-loop TUI mode"
	@echo "  make run RUN_LOOP_ARGS= - Start the TUI without auto-loop for MCP intervention"
	@echo "  make run_cli       - Run the main build workflow non-interactively"
	@echo "  make run_inc       - Incrementally modify an existing generated workflow"
	@echo "  make run_eval      - Run tools/checkers/flow/env static evaluations and aggregate reports"
	@echo "  make run_eval_tools|checkers|flow|env - Run one static evaluation in TUI"
	@echo "  make run_eval_runtime_default - Run only the generated default workflow evaluation"
	@echo "  make run_eval_runtime_inc     - Run only the generated incremental workflow evaluation"
	@echo "  make eval-review   - Interactively review, approve, reject, defer, or add suggestions"
	@echo "  make eval-list     - List current open findings and suggestions"
	@echo "  make eval-approve ID=... REASON='...' - Approve one current item"
	@echo "  make eval-reject ID=... REASON='...'  - Reject one current item"
	@echo "  make eval-suggest TITLE='...' DESCRIPTION='...' - Add a user suggestion"
	@echo "  make eval-ui       - Open the local graphical report and approval console"
	@echo "  make session       - Start TUI workflow in shared tmux"
	@echo "  make session_inc   - Start incremental workflow in shared tmux"
	@echo "  make session_eval  - Start evaluation workflow in shared tmux"
	@echo "  make session_cli   - Start non-TUI workflow in shared tmux"
	@echo "  make regression    - Run deterministic component regression"
	@echo "  make clean         - Remove generated workflow outputs and logs"

configure:
	@python3 "$(WORKFLOW_BUILDER_DIR)/setup.py"

configure-check:
	@python3 "$(WORKFLOW_BUILDER_DIR)/setup.py" --check

configure-show:
	@python3 "$(WORKFLOW_BUILDER_DIR)/setup.py" --show

prepare_input:
	@test -d "$(INPUT_DIR)" || (echo "missing input directory: $(INPUT_DIR)" && exit 1)
	@test -f "$(GUIDE_FILE)" || (echo "missing guide file: $(GUIDE_FILE)" && exit 1)
	@test -d "$(INPUT_DIR)/test_input" || (echo "missing test_input directory: $(INPUT_DIR)/test_input" && exit 1)
	@test -d "$(WFGEN_SOURCE_DIR)" || (echo "missing wfgen directory: $(WFGEN_SOURCE_DIR)" && exit 1)
	@test -d "$(GUIDE_DOC_SOURCE_DIR)" || (echo "missing Guide_Doc directory: $(GUIDE_DOC_SOURCE_DIR)" && exit 1)
	@chmod -R u+w "$(WORKSPACE_INPUT_DIR)" "$(WORKSPACE_WFGEN_DIR)" "$(WORKSPACE_GUIDE_DOC_DIR)" 2>/dev/null || true
	@mkdir -p "$(WORKSPACE_INPUT_DIR)"
	@cp -a "$(INPUT_DIR)/." "$(WORKSPACE_INPUT_DIR)/"
	@echo "[PASS] copied input from $(INPUT_DIR) to $(WORKSPACE_INPUT_DIR)"
	@mkdir -p "$(WORKSPACE_WFGEN_DIR)"
	@if [ "$$(realpath "$(WFGEN_SOURCE_DIR)")" = "$$(realpath "$(WORKSPACE_WFGEN_DIR)")" ]; then \
		echo "[PASS] wfgen already available at $(WORKSPACE_WFGEN_DIR)"; \
	else \
		cp -a "$(WFGEN_SOURCE_DIR)/." "$(WORKSPACE_WFGEN_DIR)/"; \
		echo "[PASS] copied wfgen from $(WFGEN_SOURCE_DIR) to $(WORKSPACE_WFGEN_DIR)"; \
	fi
	@mkdir -p "$(WORKSPACE_GUIDE_DOC_DIR)"
	@if [ "$$(realpath "$(GUIDE_DOC_SOURCE_DIR)")" = "$$(realpath "$(WORKSPACE_GUIDE_DOC_DIR)")" ]; then \
		echo "[PASS] Guide_Doc already available at $(WORKSPACE_GUIDE_DOC_DIR)"; \
	else \
		cp -a "$(GUIDE_DOC_SOURCE_DIR)/." "$(WORKSPACE_GUIDE_DOC_DIR)/"; \
		echo "[PASS] copied Guide_Doc from $(GUIDE_DOC_SOURCE_DIR) to $(WORKSPACE_GUIDE_DOC_DIR)"; \
	fi

prepare_workspace_state:
	@mkdir -p "$(WFB_WORKSPACE)" "$(WFB_WORKSPACE)/eval" "$(WFB_WORKSPACE)/res" "$(WFB_WORKSPACE)/tmp"
	@if [ -d "$(WFB_WORKSPACE)/.ucagent/history" ]; then \
		chmod -R u+w "$(WFB_WORKSPACE)/.ucagent/history"; \
		echo "[PASS] restored writable UCAgent history snapshots"; \
	fi
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli \
		--workspace "$(WFB_WORKSPACE)" initialize
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli \
		--workspace "$(WFB_WORKSPACE)" validate

prepare_inc_workspace: prepare_workspace_state
	@rm -rf "$(WFB_WORKSPACE)/tmp/ui_validation"
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli \
		--workspace "$(WFB_WORKSPACE)" start-inc-run

run: prepare_input prepare_workspace_state
	@mkdir -p $(WFB_WORKSPACE) $(WFB_WORKSPACE)/$(NORMALIZED_OUT) $(WFB_WORKSPACE)/.ucagent
	cd $(WFB_WORKSPACE) && { \
		PYTHONPATH="$(WORKFLOW_PYTHONPATH)" $(PYTHON) -m \
			examples.workflow_builder.workflow_builder.history_permissions \
			--path "$(WFB_WORKSPACE)/.ucagent/history" \
			--interval "$(HISTORY_GUARD_INTERVAL)" & \
		history_guard_pid=$$!; \
		trap 'kill "$$history_guard_pid" 2>/dev/null || true; wait "$$history_guard_pid" 2>/dev/null || true; chmod -R u+w "$(WFB_WORKSPACE)/.ucagent/history" 2>/dev/null || true' EXIT INT TERM; \
		PYTHONPATH="$(WORKFLOW_PYTHONPATH)" UCAGENT_OUTPUT=$(NORMALIZED_OUT) $(UCAGENT) $(WFB_WORKSPACE) $(TARGET) \
			--config $(CONFIG_FILE) \
			--output $(NORMALIZED_OUT) \
			--guid-doc-path $(GUIDE_DOC_PATH) \
			--mcp-server \
			--mcp-server-host $(MCP_SERVER_HOST) \
			--mcp-server-port $(MCP_SERVER_PORT) \
			-s -hm --no-embed-tools --tui $(RUN_LOOP_ARGS) $(RUN_EXTRA); \
		run_status=$$?; \
		kill "$$history_guard_pid" 2>/dev/null || true; \
		wait "$$history_guard_pid" 2>/dev/null || true; \
		trap - EXIT INT TERM; \
		chmod -R u+w "$(WFB_WORKSPACE)/.ucagent/history" 2>/dev/null || true; \
		exit $$run_status; \
	}

run_cli: prepare_input prepare_workspace_state
	@mkdir -p $(WFB_WORKSPACE) $(WFB_WORKSPACE)/$(NORMALIZED_OUT) $(WFB_WORKSPACE)/.ucagent
	cd $(WFB_WORKSPACE) && \
	{ PYTHONPATH="$(WORKFLOW_PYTHONPATH)" UCAGENT_OUTPUT=$(NORMALIZED_OUT) $(UCAGENT) $(WFB_WORKSPACE) $(TARGET) \
		--config $(CONFIG_FILE) \
		--output $(NORMALIZED_OUT) \
		--guid-doc-path $(GUIDE_DOC_PATH) \
		--mcp-server-port -1 \
		-s -hm --loop --loop-msg "$(RUN_LOOP_MSG)" --no-embed-tools --no-history --exit-on-completion $(RUN_EXTRA) 2>&1 \
		| tee .ucagent/run_cli.log; }; \
	grep -E "All stages completed|ToolExit|Verify Agent is exited" .ucagent/run_cli.log >/dev/null

run_inc: prepare_input prepare_inc_workspace
	@mkdir -p $(WFB_WORKSPACE) $(WFB_WORKSPACE)/$(NORMALIZED_OUT) $(WFB_WORKSPACE)/.ucagent
	@chmod -R u+w "$(WFB_WORKSPACE)/workflow" 2>/dev/null || true
	cd $(WFB_WORKSPACE) && \
	INC_RUN_ID="$$(PYTHONPATH="$(WORKFLOW_PYTHONPATH)" $(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli --workspace "$(WFB_WORKSPACE)" current-inc-run --plain)"; \
	trap 'chmod -R u+w "$(WFB_WORKSPACE)/workflow" 2>/dev/null || true' EXIT; \
	PYTHONPATH="$(WORKFLOW_PYTHONPATH)" UCAGENT_INC_RUN_ID="$$INC_RUN_ID" UCAGENT_OUTPUT=$(NORMALIZED_OUT) $(UCAGENT) $(WFB_WORKSPACE) $(TARGET)_inc \
		--config $(INC_CONFIG_FILE) --output $(NORMALIZED_OUT) --guid-doc-path $(GUIDE_DOC_PATH) \
		--mcp-server --mcp-server-port -1 \
		--loop --loop-msg "$(INC_LOOP_MSG)" \
		-s -hm --no-embed-tools --tui $(RUN_EXTRA)

run_inc_cli: prepare_input prepare_inc_workspace
	@mkdir -p $(WFB_WORKSPACE) $(WFB_WORKSPACE)/$(NORMALIZED_OUT) $(WFB_WORKSPACE)/.ucagent
	@chmod -R u+w "$(WFB_WORKSPACE)/workflow" 2>/dev/null || true
	cd $(WFB_WORKSPACE) && \
	INC_RUN_ID="$$(PYTHONPATH="$(WORKFLOW_PYTHONPATH)" $(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli --workspace "$(WFB_WORKSPACE)" current-inc-run --plain)"; \
	trap 'chmod -R u+w "$(WFB_WORKSPACE)/workflow" 2>/dev/null || true' EXIT; \
	{ PYTHONPATH="$(WORKFLOW_PYTHONPATH)" UCAGENT_INC_RUN_ID="$$INC_RUN_ID" UCAGENT_OUTPUT=$(NORMALIZED_OUT) $(UCAGENT) $(WFB_WORKSPACE) $(TARGET)_inc \
		--config $(INC_CONFIG_FILE) --output $(NORMALIZED_OUT) --guid-doc-path $(GUIDE_DOC_PATH) \
		--mcp-server-port -1 -s -hm --loop --loop-msg "$(INC_LOOP_MSG)" \
		--no-embed-tools --no-history --exit-on-completion $(RUN_EXTRA) 2>&1 \
		| tee .ucagent/run_inc_cli.log; }; \
	grep -E "All stages completed|ToolExit|Verify Agent is exited" .ucagent/run_inc_cli.log >/dev/null

define EVAL_TARGETS
run_eval_$(1): prepare_input prepare_workspace_state
	@chmod -R u+w "$(WFB_WORKSPACE)/.ucagent" 2>/dev/null || true
	@rm -rf "$(WFB_WORKSPACE)/.ucagent"
	@mkdir -p "$(WFB_WORKSPACE)/.ucagent" "$(WFB_WORKSPACE)/$(EVAL_OUTPUT_ROOT)/$(1)" "$(WFB_WORKSPACE)/$(EVAL_LOG_DIR)"
	cd "$(WFB_WORKSPACE)" && \
	PYTHONPATH="$(WORKFLOW_PYTHONPATH)" UCAGENT_OUTPUT=$(EVAL_OUTPUT_ROOT)/$(1) $(UCAGENT) "$(WFB_WORKSPACE)" "$(TARGET)_eval_$(1)" \
		--config "$($(2))" --output $(EVAL_OUTPUT_ROOT)/$(1) --guid-doc-path "$(GUIDE_DOC_PATH)" \
		--mcp-server --mcp-server-port -1 --loop --loop-msg "$(EVAL_LOOP_MSG)" \
		-s -hm --no-embed-tools --no-history --exit-on-completion --tui $(RUN_EXTRA)

run_eval_$(1)_cli: prepare_input prepare_workspace_state
	@chmod -R u+w "$(WFB_WORKSPACE)/.ucagent" 2>/dev/null || true
	@rm -rf "$(WFB_WORKSPACE)/.ucagent"
	@mkdir -p "$(WFB_WORKSPACE)/.ucagent" "$(WFB_WORKSPACE)/$(EVAL_OUTPUT_ROOT)/$(1)" "$(WFB_WORKSPACE)/$(EVAL_LOG_DIR)"
	cd "$(WFB_WORKSPACE)" && \
	{ PYTHONPATH="$(WORKFLOW_PYTHONPATH)" UCAGENT_OUTPUT=$(EVAL_OUTPUT_ROOT)/$(1) $(UCAGENT) "$(WFB_WORKSPACE)" "$(TARGET)_eval_$(1)" \
		--config "$($(2))" --output $(EVAL_OUTPUT_ROOT)/$(1) --guid-doc-path "$(GUIDE_DOC_PATH)" \
		--mcp-server-port -1 -s -hm --loop --loop-msg "$(EVAL_LOOP_MSG)" \
		--no-embed-tools --no-history --exit-on-completion $(RUN_EXTRA) 2>&1 \
		| tee "$(EVAL_LOG_DIR)/run_eval_$(1)_cli.log"; }; \
	grep -E "All stages completed|ToolExit|Verify Agent is exited" "$(EVAL_LOG_DIR)/run_eval_$(1)_cli.log" >/dev/null
endef

$(eval $(call EVAL_TARGETS,tools,EVAL_TOOLS_CONFIG_FILE))
$(eval $(call EVAL_TARGETS,checkers,EVAL_CHECKERS_CONFIG_FILE))
$(eval $(call EVAL_TARGETS,flow,EVAL_FLOW_CONFIG_FILE))
$(eval $(call EVAL_TARGETS,env,EVAL_ENV_CONFIG_FILE))

aggregate_eval:
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli \
		--workspace "$(WFB_WORKSPACE)" aggregate

run_eval: run_eval_tools run_eval_checkers run_eval_flow run_eval_env aggregate_eval

run_eval_cli: run_eval_tools_cli run_eval_checkers_cli run_eval_flow_cli run_eval_env_cli aggregate_eval

eval-review: prepare_workspace_state
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli \
		--workspace "$(WFB_WORKSPACE)" review --show-evidence

eval-list: prepare_workspace_state
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli \
		--workspace "$(WFB_WORKSPACE)" list-review

eval-approve eval-reject eval-defer: prepare_workspace_state
	@test -n "$(ID)" || (echo "ID is required" && exit 2)
	@test -n "$(REASON)" || (echo "REASON is required" && exit 2)
	@action="$(@:eval-%=%)"; cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli \
		--workspace "$(WFB_WORKSPACE)" "$$action" --id "$(ID)" --reason "$(REASON)"

eval-suggest: prepare_workspace_state
	@test -n "$(TITLE)" || (echo "TITLE is required" && exit 2)
	@test -n "$(DESCRIPTION)" || (echo "DESCRIPTION is required" && exit 2)
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli \
		--workspace "$(WFB_WORKSPACE)" suggest --title "$(TITLE)" \
		--description "$(DESCRIPTION)" --priority "$(PRIORITY)"

eval-ui: prepare_workspace_state
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.review_server \
		--workspace "$(WFB_WORKSPACE)" --host "$(EVAL_UI_HOST)" --port "$(EVAL_UI_PORT)"

define EVAL_RUNTIME_TARGETS
run_eval_runtime_$(1): prepare_input prepare_workspace_state
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli --workspace "$(WFB_WORKSPACE)" \
		request-run --mode $(1) --workflow-root workflow --target example
	@chmod -R u+w "$(WFB_WORKSPACE)/.ucagent" 2>/dev/null || true
	@rm -rf "$(WFB_WORKSPACE)/.ucagent"
	@mkdir -p "$(WFB_WORKSPACE)/.ucagent" "$(WFB_WORKSPACE)/$(EVAL_OUTPUT_ROOT)/run_$(1)" "$(WFB_WORKSPACE)/$(EVAL_LOG_DIR)"
	cd "$(WFB_WORKSPACE)" && \
	PYTHONPATH="$(WORKFLOW_PYTHONPATH)" UCAGENT_OUTPUT=$(EVAL_OUTPUT_ROOT)/run_$(1) $(UCAGENT) "$(WFB_WORKSPACE)" "$(TARGET)_eval_run_$(1)" \
		--config "$(EVAL_RUN_CONFIG_FILE)" --output $(EVAL_OUTPUT_ROOT)/run_$(1) --guid-doc-path "$(GUIDE_DOC_PATH)" \
		--mcp-server --mcp-server-port -1 --loop --loop-msg "$(EVAL_LOOP_MSG)" \
		-s -hm --no-embed-tools --no-history --exit-on-completion --tui $(RUN_EXTRA)

run_eval_runtime_$(1)_cli: prepare_input prepare_workspace_state
	@cd "$(WFB_WORKSPACE)" && PYTHONPATH="$(WORKFLOW_PYTHONPATH)" \
		$(PYTHON) -m examples.workflow_builder.workflow_evaluation_control.cli --workspace "$(WFB_WORKSPACE)" \
		request-run --mode $(1) --workflow-root workflow --target example
	@chmod -R u+w "$(WFB_WORKSPACE)/.ucagent" 2>/dev/null || true
	@rm -rf "$(WFB_WORKSPACE)/.ucagent"
	@mkdir -p "$(WFB_WORKSPACE)/.ucagent" "$(WFB_WORKSPACE)/$(EVAL_OUTPUT_ROOT)/run_$(1)" "$(WFB_WORKSPACE)/$(EVAL_LOG_DIR)"
	cd "$(WFB_WORKSPACE)" && \
	{ PYTHONPATH="$(WORKFLOW_PYTHONPATH)" UCAGENT_OUTPUT=$(EVAL_OUTPUT_ROOT)/run_$(1) $(UCAGENT) "$(WFB_WORKSPACE)" "$(TARGET)_eval_run_$(1)" \
		--config "$(EVAL_RUN_CONFIG_FILE)" --output $(EVAL_OUTPUT_ROOT)/run_$(1) --guid-doc-path "$(GUIDE_DOC_PATH)" \
		--mcp-server-port -1 -s -hm --loop --loop-msg "$(EVAL_LOOP_MSG)" \
		--no-embed-tools --no-history --exit-on-completion $(RUN_EXTRA) 2>&1 \
		| tee "$(EVAL_LOG_DIR)/run_eval_run_$(1)_cli.log"; }; \
	grep -E "All stages completed|ToolExit|Verify Agent is exited" "$(EVAL_LOG_DIR)/run_eval_run_$(1)_cli.log" >/dev/null
endef

$(eval $(call EVAL_RUNTIME_TARGETS,default))
$(eval $(call EVAL_RUNTIME_TARGETS,inc))

session: prepare_workspace_state
	@tmux has-session -t $(SESSION) 2>/dev/null && tmux kill-session -t $(SESSION) || true
	@mkdir -p $(WFB_WORKSPACE)
	@tmux new-session -d -s $(SESSION) -c $(WFB_WORKSPACE) bash
	@tmux send-keys -t $(SESSION) 'export TERM=xterm-256color COLORTERM=truecolor FORCE_COLOR=1' C-m
	@tmux send-keys -t $(SESSION) 'make -f $(WORKFLOW_BUILDER_HOME)/Makefile run WFB_WORKSPACE=$(WFB_WORKSPACE) OUT=$(OUT)' C-m
	@echo "Observe: tmux attach -t $(SESSION) -r"

session_cli: prepare_workspace_state
	@tmux has-session -t $(SESSION)_cli 2>/dev/null && tmux kill-session -t $(SESSION)_cli || true
	@mkdir -p $(WFB_WORKSPACE)
	@tmux new-session -d -s $(SESSION)_cli -c $(WFB_WORKSPACE) bash
	@tmux send-keys -t $(SESSION)_cli 'export TERM=xterm-256color COLORTERM=truecolor FORCE_COLOR=1' C-m
	@tmux send-keys -t $(SESSION)_cli 'make -f $(WORKFLOW_BUILDER_HOME)/Makefile run_cli WFB_WORKSPACE=$(WFB_WORKSPACE) OUT=$(OUT)' C-m
	@echo "Observe: tmux attach -t $(SESSION)_cli -r"

session_inc: prepare_workspace_state
	@tmux has-session -t $(INC_SESSION) 2>/dev/null && tmux kill-session -t $(INC_SESSION) || true
	@mkdir -p $(WFB_WORKSPACE)
	@tmux new-session -d -s $(INC_SESSION) -c $(WFB_WORKSPACE) bash
	@tmux send-keys -t $(INC_SESSION) 'export TERM=xterm-256color COLORTERM=truecolor FORCE_COLOR=1' C-m
	@tmux send-keys -t $(INC_SESSION) 'make -f $(WORKFLOW_BUILDER_HOME)/Makefile run_inc WFB_WORKSPACE=$(WFB_WORKSPACE) OUT=$(OUT)' C-m
	@echo "Observe: tmux attach -t $(INC_SESSION) -r"

session_eval: prepare_workspace_state
	@tmux has-session -t $(EVAL_SESSION) 2>/dev/null && tmux kill-session -t $(EVAL_SESSION) || true
	@mkdir -p $(WFB_WORKSPACE)
	@tmux new-session -d -s $(EVAL_SESSION) -c $(WFB_WORKSPACE) bash
	@tmux send-keys -t $(EVAL_SESSION) 'export TERM=xterm-256color COLORTERM=truecolor FORCE_COLOR=1' C-m
	@tmux send-keys -t $(EVAL_SESSION) 'make -f $(WORKFLOW_BUILDER_HOME)/Makefile run_eval WFB_WORKSPACE=$(WFB_WORKSPACE) OUT=$(OUT)' C-m
	@echo "Observe: tmux attach -t $(EVAL_SESSION) -r"

regression:
	$(MAKE) -C $(WORKFLOW_BUILDER_HOME)/regression PYTHON="$(PYTHON)" all

clean:
	@rm -rf "$(WFB_WORKSPACE)/.ucagent" "$(WFB_WORKSPACE)/workflow"
	@mkdir -p "$(WFB_WORKSPACE)/tmp"
	@find "$(WFB_WORKSPACE)/tmp" -mindepth 1 -maxdepth 1 ! -name inc_runs ! -name change_history -exec rm -rf {} +
	@echo "[PASS] removed generated workflow and disposable runtime files; preserved eval/, res/, input/, and incremental version history"
