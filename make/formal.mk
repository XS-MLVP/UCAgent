# Formal verification workspaces and launch modes.

## Formal verification
FORMAL_DIR   := examples/Formal
FORMAL_CWD   ?= $(FORMAL_DIR)/output/workspace_$*
FORMAL_CMD = $(CMD) $(FORMAL_CWD)/ $* --plugin ucagent/plugins/Formal --plugin-workflow formal:formal -s -hm --tui

formal_init_%: ## Prepare a formal verification workspace
	mkdir -p $(FORMAL_CWD)
	cp -r $(FORMAL_DIR)/$* $(FORMAL_CWD)/

formal_%: formal_init_% ## Start formal verification via the Formal plugin
	$(FORMAL_CMD) --output formal_test $(ARGS)

formal_mcp_%: formal_init_% ## Start formal verification in MCP mode
	$(FORMAL_CMD) --mcp-server-no-file-tools --output formal_test --mcp-server-port 5000 --master 127.0.0.1 --export-cmd-api --use-skill --log $(ARGS)

clean_formal: ## Remove all formal verification workspaces
	rm -rf $(FORMAL_DIR)/output
