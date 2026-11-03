# Formal verification workspaces and launch modes.

## Formal verification
FORMAL_DIR   := examples/Formal
FORMAL_CWD   ?= $(FORMAL_DIR)/output/workspace_$*
FORMAL_CFG   := ucagent/lang/zh/config/formal.yaml
FORMAL_DOC   := ucagent/lang/zh/doc/Formal_Doc

FORMAL_CMD = $(CMD) $(FORMAL_CWD)/ $* --config $(FORMAL_CFG) -s -hm --tui

formal_init_%: ## Prepare a formal verification workspace
	mkdir -p $(FORMAL_CWD)
	cp -r $(FORMAL_DIR)/$* $(FORMAL_CWD)/

formal_%: formal_init_% ## Start formal verification
	$(FORMAL_CMD) --guid-doc-path $(FORMAL_DOC)/ --output formal_test $(ARGS)

formal_mcp_%: formal_init_% ## Start formal verification in MCP mode
	$(FORMAL_CMD) --mcp-server-no-file-tools --guid-doc-path $(FORMAL_DOC)/ --output formal_test --mcp-server-port 5000 --master 127.0.0.1 --export-cmd-api --use-skill --log $(ARGS)

clean_formal: ## Remove all formal verification workspaces
	rm -rf $(FORMAL_DIR)/output
