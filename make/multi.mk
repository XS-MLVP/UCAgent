# Three-layer multi-agent launch targets.
#
# The repository Makefile includes this file. It can also be used directly:
#   make -f make/multi.mk multi_help
#
# MULTI_CONFIG must be the normal UCAgent config file (or a file that also
# contains the model/backend settings). Use MULTI_ARGS for extra UCAgent flags
# and MULTI_OVERRIDES for additional --override arguments.

## Multi Agent
ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
PYTHON ?= python3
MULTI_PYTHON ?= $(if $(wildcard $(ROOT_DIR)/.venv/bin/python),$(ROOT_DIR)/.venv/bin/python,$(PYTHON))
MULTI_UCAGENT ?= $(MULTI_PYTHON) "$(ROOT_DIR)/ucagent.py"

MULTI_WORKSPACE ?= $(ROOT_DIR)/output/workspace_multi
MULTI_DUT ?= mission
MULTI_CONFIG ?= $(ROOT_DIR)/config.yaml
MULTI_PROMPT ?=
MULTI_PLUGIN ?= $(ROOT_DIR)/ucagent/plugins/UnitTest
MULTI_WORKFLOW ?= unittest:unittest
MULTI_TASK_WORKFLOW ?=

# These overrides apply to the standard launch profile and session limits.
MULTI_BACKEND ?=
MULTI_MAX_SUBAGENTS ?=
MULTI_MAX_PARALLEL ?=
MULTI_MAX_RUNS ?=
MULTI_UI ?= --tui
MULTI_ARGS ?=
MULTI_OVERRIDES ?=
MULTI_MCP_SERVER ?=

MULTI_WORKSPACE_ABS = $(abspath $(MULTI_WORKSPACE))
MULTI_POLICY_OVERRIDES = \
	$(if $(MULTI_PLUGIN),--override 'global_agent.plugin_selectors=["$(MULTI_PLUGIN)"]',) \
	$(if $(MULTI_WORKFLOW),--override 'global_agent.allowed_workflows=["$(MULTI_WORKFLOW)"]',)
MULTI_LIMIT_OVERRIDES = \
	$(if $(MULTI_BACKEND),--backend $(MULTI_BACKEND),) \
	$(if $(MULTI_MAX_SUBAGENTS),--max-subagents $(MULTI_MAX_SUBAGENTS),) \
	$(if $(MULTI_MAX_PARALLEL),--override 'global_agent.max_parallel_supers=$(MULTI_MAX_PARALLEL)',) \
	$(if $(MULTI_MAX_RUNS),--override 'global_agent.max_runs_per_request=$(MULTI_MAX_RUNS)',)

MULTI_LAUNCH = $(MULTI_UCAGENT) "$(MULTI_WORKSPACE_ABS)/" "$(MULTI_DUT)" \
	--agent-mode multi \
	--config "$(MULTI_CONFIG)" \
	$(MULTI_POLICY_OVERRIDES) \
	$(if $(MULTI_TASK_WORKFLOW),--plugin-workflow $(MULTI_TASK_WORKFLOW),) \
	$(MULTI_LIMIT_OVERRIDES) \
	$(MULTI_OVERRIDES) \
	$(MULTI_MCP_SERVER) \
	$(if $(strip $(MULTI_PROMPT)),--loop-msg "$(MULTI_PROMPT)",) \
	$(MULTI_UI) $(MULTI_ARGS)

multi: ## Launch idle Global with UnitTest in its workflow catalog
	@test -f "$(MULTI_CONFIG)" || { echo "Error: config not found: $(MULTI_CONFIG)"; echo "Set MULTI_CONFIG=/path/to/config.yaml"; exit 1; }
	@mkdir -p "$(MULTI_WORKSPACE_ABS)"
	$(MULTI_LAUNCH)

multi_interactive: MULTI_UI := --human
multi_interactive: multi ## Launch Global Agent with the interactive console

multi_tui: MULTI_UI := --tui
multi_tui: multi ## Launch Global Agent with the TUI

multi_unit: MULTI_PLUGIN := $(ROOT_DIR)/ucagent/plugins/UnitTest
multi_unit: MULTI_WORKFLOW := unittest:unittest
multi_unit: MULTI_PROMPT := 使用指定的 UnitTest 工作流验证当前 DUT，并完成任务
multi_unit: MULTI_TASK_WORKFLOW = $(MULTI_WORKFLOW)
multi_unit: multi ## Launch the bundled UnitTest workflow explicitly

multi_formal: MULTI_PLUGIN := $(ROOT_DIR)/ucagent/plugins/Formal
multi_formal: MULTI_WORKFLOW := formal:formal
multi_formal: MULTI_PROMPT := 为当前 DUT 生成形式化属性、脚本和覆盖证据，并完成验证
multi_formal: MULTI_TASK_WORKFLOW = $(MULTI_WORKFLOW)
multi_formal: multi ## Launch the Formal workflow

multi_rtl2spec: MULTI_PLUGIN := $(ROOT_DIR)/ucagent/plugins/RTL2Spec
multi_rtl2spec: MULTI_WORKFLOW := rtl2spec:generic-design-document
multi_rtl2spec: MULTI_PROMPT := 为当前 RTL 生成有证据支撑的设计与功能检查点文档
multi_rtl2spec: MULTI_TASK_WORKFLOW = $(MULTI_WORKFLOW)
multi_rtl2spec: multi ## Launch the RTL2Spec generic document workflow

multi_ppa: MULTI_PLUGIN := $(ROOT_DIR)/ucagent/plugins/DesignWithPPA
multi_ppa: MULTI_WORKFLOW := design-with-ppa:unit-design-tdd
multi_ppa: MULTI_PROMPT := 通过 TDD、覆盖率和 PPA 迭代完成当前单元设计
multi_ppa: MULTI_TASK_WORKFLOW = $(MULTI_WORKFLOW)
multi_ppa: multi ## Launch the DesignWithPPA unit-design workflow

multi_check: ## Validate Global Agent paths without starting a model
	@test -f "$(MULTI_CONFIG)" || { echo "Error: config not found: $(MULTI_CONFIG)"; exit 1; }
	@echo "workspace: $(MULTI_WORKSPACE_ABS)"
	@echo "config:    $(MULTI_CONFIG)"
	@if [ -e "$(MULTI_PLUGIN)" ]; then \
		echo "plugin:    $(MULTI_PLUGIN)"; \
	else \
		echo "plugin:    $(MULTI_PLUGIN) (selector; resolved by UCAgent)"; \
	fi
	@echo "workflow:  $(MULTI_WORKFLOW)"

multi_help: ## Show Global Agent launch examples
	@printf '%s\n' \
		'Usage: make <target> [VARIABLE=value ...]' \
		'' \
		'Common variables:' \
		'  MULTI_WORKSPACE   workspace directory (default: output/workspace_multi)' \
		'  MULTI_DUT         DUT name (default: mission)' \
		'  MULTI_CONFIG      config file with model settings and workflow policy' \
		'  MULTI_PROMPT      first natural-language goal' \
		'  MULTI_PLUGIN      plugin path or selector' \
		'  MULTI_WORKFLOW    plugin:workflow available in the catalog' \
		'  MULTI_TASK_WORKFLOW  exact startup workflow; empty keeps Global idle' \
		'  MULTI_BACKEND     default backend for Global, Super and Sub' \
		'  MULTI_MAX_SUBAGENTS / MULTI_MAX_PARALLEL / MULTI_MAX_RUNS' \
		'  MULTI_ARGS        extra UCAgent flags, e.g. --backend codex' \
		'  MULTI_MCP_SERVER  optional explicit MCP flags (CLI backends enable MCP automatically)' \
		'' \
		'Examples:' \
		'  make multi' \
		'  make multi_interactive' \
		'  make multi MULTI_WORKSPACE=output/workspace_Adder MULTI_DUT=Adder' \
		'  make multi MULTI_CONFIG=./my-multi-config.yaml MULTI_PROMPT="先分析再验证"' \
		'  make multi_formal MULTI_WORKSPACE=... MULTI_DUT=...' \
		'  make multi_rtl2spec MULTI_CONFIG=...' \
		'  make multi MULTI_BACKEND=codex MULTI_MAX_SUBAGENTS=2 MULTI_MAX_PARALLEL=2' \
		'  make multi_check'
