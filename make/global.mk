# Global Agent launch targets.
#
# The repository Makefile includes this file. It can also be used directly:
#   make -f make/global.mk global_help
#
# GLOBAL_CONFIG must be the normal UCAgent config file (or a file that also
# contains the model/backend settings). Use GLOBAL_ARGS for extra UCAgent flags
# and GLOBAL_OVERRIDES for additional --override arguments.

## Global Agent
ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
PYTHON ?= python3
GLOBAL_PYTHON ?= $(if $(wildcard $(ROOT_DIR)/.venv/bin/python),$(ROOT_DIR)/.venv/bin/python,$(PYTHON))
GLOBAL_UCAGENT ?= $(GLOBAL_PYTHON) "$(ROOT_DIR)/ucagent.py"

GLOBAL_WORKSPACE ?= $(ROOT_DIR)/output/workspace_global
GLOBAL_DUT ?= mission
GLOBAL_CONFIG ?= $(ROOT_DIR)/config.yaml
GLOBAL_PROMPT ?=
GLOBAL_PLUGIN ?= $(ROOT_DIR)/ucagent/plugins/UnitTest
GLOBAL_WORKFLOW ?= unittest:unittest

# These overrides apply to the standard launch profile and session limits.
GLOBAL_BACKEND ?=
GLOBAL_MAX_SUBAGENTS ?=
GLOBAL_MAX_PARALLEL ?=
GLOBAL_MAX_RUNS ?=
GLOBAL_UI ?= --tui
GLOBAL_ARGS ?=
GLOBAL_OVERRIDES ?=
GLOBAL_MCP_SERVER ?= --mcp-server --mcp-server-port 0

GLOBAL_WORKSPACE_ABS = $(abspath $(GLOBAL_WORKSPACE))
GLOBAL_POLICY_OVERRIDES = \
	$(if $(GLOBAL_PLUGIN),--override 'global_agent.plugin_selectors=["$(GLOBAL_PLUGIN)"]',) \
	$(if $(GLOBAL_WORKFLOW),--override 'global_agent.allowed_workflows=["$(GLOBAL_WORKFLOW)"]',)
GLOBAL_LIMIT_OVERRIDES = \
	$(if $(GLOBAL_BACKEND),--override 'global_agent.launch_profiles.standard.backend=$(GLOBAL_BACKEND)',) \
	$(if $(GLOBAL_MAX_SUBAGENTS),--override 'global_agent.launch_profiles.standard.max_subagents=$(GLOBAL_MAX_SUBAGENTS)',) \
	$(if $(GLOBAL_MAX_PARALLEL),--override 'global_agent.max_parallel_supers=$(GLOBAL_MAX_PARALLEL)',) \
	$(if $(GLOBAL_MAX_RUNS),--override 'global_agent.max_runs_per_request=$(GLOBAL_MAX_RUNS)',)

GLOBAL_LAUNCH = $(GLOBAL_UCAGENT) "$(GLOBAL_WORKSPACE_ABS)/" "$(GLOBAL_DUT)" \
	--agent-mode global \
	--config "$(GLOBAL_CONFIG)" \
	$(GLOBAL_POLICY_OVERRIDES) \
	$(GLOBAL_LIMIT_OVERRIDES) \
	$(GLOBAL_OVERRIDES) \
	$(GLOBAL_MCP_SERVER) \
	$(if $(strip $(GLOBAL_PROMPT)),--loop-msg "$(GLOBAL_PROMPT)",) \
	$(GLOBAL_UI) $(GLOBAL_ARGS)

global: ## Launch Global Agent with the default UnitTest workflow
	@test -f "$(GLOBAL_CONFIG)" || { echo "Error: config not found: $(GLOBAL_CONFIG)"; echo "Set GLOBAL_CONFIG=/path/to/config.yaml"; exit 1; }
	@mkdir -p "$(GLOBAL_WORKSPACE_ABS)"
	$(GLOBAL_LAUNCH)

global_interactive: GLOBAL_UI := --human
global_interactive: global ## Launch Global Agent with the interactive console

global_tui: GLOBAL_UI := --tui
global_tui: global ## Launch Global Agent with the TUI

global_unit: GLOBAL_PLUGIN := $(ROOT_DIR)/ucagent/plugins/UnitTest
global_unit: GLOBAL_WORKFLOW := unittest:unittest
global_unit: GLOBAL_PROMPT := 先分析当前 DUT，选择合适的验证工作流并完成任务
global_unit: global ## Launch the bundled UnitTest workflow explicitly

global_formal: GLOBAL_PLUGIN := $(ROOT_DIR)/ucagent/plugins/Formal
global_formal: GLOBAL_WORKFLOW := formal:formal
global_formal: GLOBAL_PROMPT := 为当前 DUT 生成形式化属性、脚本和覆盖证据，并完成验证
global_formal: global ## Launch the Formal workflow

global_rtl2spec: GLOBAL_PLUGIN := $(ROOT_DIR)/ucagent/plugins/RTL2Spec
global_rtl2spec: GLOBAL_WORKFLOW := rtl2spec:generic-design-document
global_rtl2spec: GLOBAL_PROMPT := 为当前 RTL 生成有证据支撑的设计与功能检查点文档
global_rtl2spec: global ## Launch the RTL2Spec generic document workflow

global_ppa: GLOBAL_PLUGIN := $(ROOT_DIR)/ucagent/plugins/DesignWithPPA
global_ppa: GLOBAL_WORKFLOW := design-with-ppa:unit-design-tdd
global_ppa: GLOBAL_PROMPT := 通过 TDD、覆盖率和 PPA 迭代完成当前单元设计
global_ppa: global ## Launch the DesignWithPPA unit-design workflow

global_check: ## Validate Global Agent paths without starting a model
	@test -f "$(GLOBAL_CONFIG)" || { echo "Error: config not found: $(GLOBAL_CONFIG)"; exit 1; }
	@echo "workspace: $(GLOBAL_WORKSPACE_ABS)"
	@echo "config:    $(GLOBAL_CONFIG)"
	@if [ -e "$(GLOBAL_PLUGIN)" ]; then \
		echo "plugin:    $(GLOBAL_PLUGIN)"; \
	else \
		echo "plugin:    $(GLOBAL_PLUGIN) (selector; resolved by UCAgent)"; \
	fi
	@echo "workflow:  $(GLOBAL_WORKFLOW)"

global_help: ## Show Global Agent launch examples
	@printf '%s\n' \
		'Usage: make <target> [VARIABLE=value ...]' \
		'' \
		'Common variables:' \
		'  GLOBAL_WORKSPACE   workspace directory (default: output/workspace_global)' \
		'  GLOBAL_DUT         DUT name (default: mission)' \
		'  GLOBAL_CONFIG      config file with model settings and workflow policy' \
		'  GLOBAL_PROMPT      first natural-language goal' \
		'  GLOBAL_PLUGIN      plugin path or selector' \
		'  GLOBAL_WORKFLOW    plugin:workflow reference' \
		'  GLOBAL_BACKEND     child Super backend override' \
		'  GLOBAL_MAX_SUBAGENTS / GLOBAL_MAX_PARALLEL / GLOBAL_MAX_RUNS' \
		'  GLOBAL_ARGS        extra UCAgent flags, e.g. --backend codex' \
		'  GLOBAL_MCP_SERVER  parent MCP flag (default: --mcp-server; required by Codex)' \
		'' \
		'Examples:' \
		'  make global' \
		'  make global_interactive' \
		'  make global GLOBAL_WORKSPACE=output/workspace_Adder GLOBAL_DUT=Adder' \
		'  make global GLOBAL_CONFIG=./my-global-config.yaml GLOBAL_PROMPT="先分析再验证"' \
		'  make global_formal GLOBAL_WORKSPACE=... GLOBAL_DUT=...' \
		'  make global_rtl2spec GLOBAL_CONFIG=...' \
		'  make global GLOBAL_BACKEND=codex GLOBAL_MAX_SUBAGENTS=2 GLOBAL_MAX_PARALLEL=2' \
		'  make global_check'
