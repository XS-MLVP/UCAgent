APORT != bash -c '\
for try in $$(seq 1 100); do \
	cand=$$(shuf -i 2000-65000 -n 1); \
	if ! ss -ltn | awk '\''{print $$4}'\'' | grep -Eq "[.:]$${cand}$$"; then \
		echo $$cand; \
		exit 0; \
	fi; \
done; \
exit 1'

ifeq ($(strip $(APORT)),)
$(error Failed to find a free local port for MCP server)
endif

clean:
	make -C ../../ clean

# command to run MCP Adder server
mcp_cmd = make -C ../../ mcp_Adder
mcp_cwd = output/Adder_$(APORT)
ifw_cfg = ~/.iflow/settings.json
ifw_prt = 5000# original mcp port in iflow settings.json

bash_iflow_wait = while [ ! -f 'Guide_Doc/dut_fixture.md' ]; do \
		sleep 5; \
	done;(sleep 10; tmux send-keys \`ucagent --hook-message cagent_init\`; sleep 1; tmux send-keys Enter)& \
	npx -y @iflow-ai/iflow-cli@latest -y


api_mul: clean
	tmux kill-session -t my_multi_api_session || true
	tmux new-session -d -s my_multi_api_session
	tmux send-keys -t my_multi_api_session:0.0 ". IFLOW_env.bash;make -C ../../ test_Adder ARGS='--no-embed-tools' CWD=output/A" C-m
	tmux split-window -h -t my_multi_api_session:0.0
	tmux send-keys -t my_multi_api_session:0.1 "sleep 10; . IFLOW_env.bash;make -C ../../ test_Mux ARGS='--no-embed-tools' CWD=output/B" C-m
	tmux attach-session -t my_multi_api_session


mcp_mul: clean
	# acquire an available local TCP port for the MCP server
	@echo "Selected MCP port: $(APORT)"
	tmux kill-session -t my_multi_mcp_session_$(APORT) || true

	# start mcp in tmux
	tmux new-session -d -s my_multi_mcp_session_$(APORT)
	tmux send-keys -t my_multi_mcp_session_$(APORT):0.0 "$(mcp_cmd) ARGS='--mcp-server-port=$(APORT)' CWD=$(mcp_cwd)" C-m

	# copy iflow settings to CWD and modify port
	mkdir -p ../../$(mcp_cwd)/.iflow
	cp $(ifw_cfg) ../../$(mcp_cwd)/.iflow/settings.json
	sed -i "s/$(ifw_prt)\/mcp/$(APORT)\/mcp/" ../../$(mcp_cwd)/.iflow/settings.json

	# start iflow in another tmux pane
	tmux split-window -h -t my_multi_mcp_session_$(APORT):0.0
	tmux send-keys -t my_multi_mcp_session_$(APORT):0.1 "cd ../../$(mcp_cwd);$(bash_iflow_wait)" C-m
	tmux attach-session -t my_multi_mcp_session_$(APORT)

