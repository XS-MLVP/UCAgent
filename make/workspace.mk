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
# Waveform defaults follow ucagent/util/test_tools.py; gsim also uses fst.
SIM_WAVEFORM_SUFFIX_verilator := fst
SIM_WAVEFORM_SUFFIX_gsim := fst
SIM_WAVEFORM_SUFFIX_vcs := fsdb
SIM_WAVEFORM_SUFFIX_uvs := usdb
WAVEFORM_SUFFIX = $(or $(SIM_WAVEFORM_SUFFIX_$(SIM)),$(error Unsupported SIM '$(SIM)'; use verilator, gsim, vcs or uvs))

# Keep stem-dependent values recursive for each DUT target.
WORKSPACE_CMD = $(CMD) $(CWD)/ $* --config $(CFG) -s -hm --tui

# Workspace assets
refresh_%: ## Remove copied Guide_Doc and skills; restart UCAgent to refresh
	$(PYTHON) ucagent/scripts/refresh_workspace_assets.py --workspace "$(CWD)" --guide-doc-cache "$(GUIDE_DOC_CACHE)"

init_%: ## Prepare the DUT workspace and export the simulator interface
	mkdir -p $(CWD)/$*_RTL
	cp $(SRC)/$*/*.v $(CWD)/$*_RTL/ || true
	cp $(SRC)/$*/*.sv $(CWD)/$*_RTL/ || true
	cp $(SRC)/$*/*.vh $(CWD)/$*_RTL/ || true
	cp $(SRC)/$*/*.scala $(CWD)/$*_RTL/ || true
	cp $(SRC)/$*/filelist.txt $(CWD)/$*_RTL/ || true
	@if [ -d $(SRC)/$*/Doc ]; then \
		echo "Copying Doc files from $(SRC)/$*/Doc to $(CWD)/$*_Doc/"; \
		cp -r $(SRC)/$*/Doc $(CWD)/$*_Doc/ || true; \
	fi
	@if [ ! -d $(CWD)/$* ]; then \
		option_fs=""; \
		if [ -f $(CWD)/$*_RTL/filelist.txt ]; then \
			option_fs="--fs $(CWD)/$*_RTL/filelist.txt"; \
		fi; \
		if [ -f $(CWD)/$*_RTL/$*.v ]; then \
			picker export $(CWD)/$*_RTL/$*.v --sim $(SIM) --rw 1 --sname $* --tdir $(CWD)/ -c -w $(CWD)/$*/$*.$(WAVEFORM_SUFFIX) $$option_fs; \
		elif [ -f $(CWD)/$*_RTL/$*.sv ]; then \
			picker export $(CWD)/$*_RTL/$*.sv --sim $(SIM) --rw 1 --sname $* --tdir $(CWD)/ -c -w $(CWD)/$*/$*.$(WAVEFORM_SUFFIX) $$option_fs; \
		fi; \
	fi
	cp $(SRC)/$*/*.md $(CWD)/$*/  || true
	cp $(SRC)/$*/*.py $(CWD)/$*/  || true
	@if [ $(BBV) = "true" ]; then \
		echo "Enable BBV mode: clear RTL files"; \
		for f in $(CWD)/$*/$*.v $(CWD)/$*/$*.sv $(CWD)/$*/$*.vh; do \
			if [ -f $$f ]; then \
				echo "clear file $$f"; \
				echo "" > $$f; \
			fi; \
		done; \
		for f in `find $(CWD)/$*_RTL/*|grep -v '.scala'`; do \
			echo "" > $$f; \
		done; \
	fi
	@python3 $(CWD)/$*/example.py || { echo "Error: picker try to generate DUT, but failed.\n"; exit 1; }

# Verification modes
test_%: init_% ## Run verification in automatic loop mode
	$(WORKSPACE_CMD) -l ${ARGS}

test_multi_%: BACKEND ?= langchain
test_multi_%: init_% ## Run multi-agent verification; MAX_SUBAGENTS caps workers
	$(WORKSPACE_CMD) -l --agent-mode multi --backend $(BACKEND) --max-subagents $(MAX_SUBAGENTS) --no-embed-tools --log ${ARGS}

test_with_master_%: init_% ## Run verification connected to MASTER_IP
	$(WORKSPACE_CMD) -l --master ${MASTER_IP} --export-cmd-api  ${ARGS}

mcp_%: init_% ## Start MCP mode without file tools
	$(WORKSPACE_CMD) --mcp-server-no-file-tools ${ARGS}

mcp_multi_%: BACKEND ?= codex
mcp_multi_%: init_% ## Run Super planning automatically and expose supervisor MCP tools
	$(WORKSPACE_CMD) -l --mcp-server --agent-mode multi --backend $(BACKEND) --max-subagents $(MAX_SUBAGENTS) --no-embed-tools --log ${ARGS}

mcp_with_master_%: init_% ## Start MCP mode connected to MASTER_IP
	$(WORKSPACE_CMD) --mcp-server-no-file-tools --master ${MASTER_IP} --export-cmd-api ${ARGS}

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
