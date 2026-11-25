# DUT workspace preparation, verification, and cleanup.

## DUT verification
CWD ?= output/workspace_$*
GUIDE_DOC_CACHE ?= Guide_Doc
CFG ?= config.yaml
BBV ?= false
MAX_SUBAGENTS ?= 2
SRC ?= examples
# Select the picker simulator, for example: make init_Adder SIM=vcs.
SIM ?= verilator

# Keep stem-dependent values recursive for each DUT target.
WORKSPACE_CMD = $(CMD) $(CWD)/ $* --config $(CFG) -s -hm --tui

# Workspace assets
refresh_%: ## Remove copied Guide_Doc and skills; restart UCAgent to refresh
	$(PYTHON) ucagent/scripts/refresh_workspace_assets.py --workspace "$(CWD)" --guide-doc-cache "$(GUIDE_DOC_CACHE)"

init_%: ## Prepare the DUT workspace and export the simulator interface
	$(PYTHON) -m ucagent prepare-workspace --plugin ucagent/plugins/UnitTest --workflow unittest --source "$(SRC)/$*" --workspace "$(CWD)" --dut "$*" --options '{"simulator":"$(SIM)","blackbox":$(BBV)}'

# Verification modes
test_%: init_% ## Run verification in automatic loop mode
	$(WORKSPACE_CMD) -l ${ARGS}

test_multi_%: BACKEND ?= langchain
test_multi_%: init_% ## Run Global/Super/Sub verification; MAX_SUBAGENTS caps each Super
	$(WORKSPACE_CMD) -l --agent-mode multi --plugin-workflow $(or $(MULTI_WORKFLOW),unittest:unittest) --backend $(BACKEND) --max-subagents $(MAX_SUBAGENTS) --no-embed-tools --log ${ARGS}

test_with_master_%: init_% ## Run verification connected to MASTER_IP
	$(WORKSPACE_CMD) -l --master ${MASTER_IP} --export-cmd-api  ${ARGS}

mcp_%: init_% ## Start MCP mode with workflow-required file tools
	$(WORKSPACE_CMD) --mcp-server ${ARGS}

mcp_multi_%: BACKEND ?= codex
mcp_multi_%: init_% ## Run Global/Super/Sub verification and expose Global MCP tools
	$(WORKSPACE_CMD) -l --mcp-server --agent-mode multi --plugin-workflow $(or $(MULTI_WORKFLOW),unittest:unittest) --backend $(BACKEND) --max-subagents $(MAX_SUBAGENTS) --no-embed-tools --log ${ARGS}

mcp_with_master_%: init_% ## Start MCP mode connected to MASTER_IP
	$(WORKSPACE_CMD) --mcp-server --master ${MASTER_IP} --export-cmd-api ${ARGS}

mcp_all_tools_%: init_% ## Start MCP mode with all tools
	$(WORKSPACE_CMD) --mcp-server ${ARGS}

continue_%: ## Resume a workspace; set DUT=<name> and ARGS as needed
	$(CMD) $(CWD)/ ${DUT} --config config.yaml ${ARGS}

# Workspace cleanup
reset_%: ## Remove generated tests, agent state, reports, and workspace Markdown
	rm $(CWD)/unit_test -rf  || true
	rm $(CWD)/.ucagent -rf  || true
	rm $(CWD)/uc_test_report -rf  || true
	rm $(CWD)/*.md -rf  || true

clean_%: ## Remove the entire DUT workspace
	rm -rf $(CWD)

clean_test_%: ## Remove only the generated unit_test directory
	rm -rf $(CWD)/unit_test
