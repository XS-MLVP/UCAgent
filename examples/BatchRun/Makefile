
APORT=5001# new port to avoid conflict
OPORT=5000# original iflow port in settings.json

clean:
	rm output -rf

init: clean
	mkdir -p output

api_batch: init
	make -C ../../ clean
	make -C ../../ test_Adder ARGS="-eoc --no-embed-tools"
	cp -r ../../output output/Adder
	make -C ../../ clean
	make -C ../../ test_Mux ARGS="-eoc --no-embed-tools"
	cp -r ../../output output/Mux
	make -C ../../ clean
	make -C ../../ test_FSM ARGS="-eoc --no-embed-tools"
	cp -r ../../output output/FSM

mcp_one_%:
	@echo "Selected MCP port: $(APORT)"
	make -C ../../ clean
	make -C ../../ mcp_$* ARGS="-eoc --mcp-server-port=$(APORT)"
	cp -r ../../output output/$*
	@while [ ! -f "../../output/exited.txt" ]; do \
		sleep 5; \
	done
	make -C ../../ clean

mcp_batch: init
	@$(MAKE) mcp_one_Adder
	@$(MAKE) mcp_one_Mux
	@$(MAKE) mcp_one_FSM

iflow_once:
	@while [ -f "../../output/.ucagent_info.json" ]; do \
		sleep 5; \
	done
	@while [ ! -f "../../output/Guide_Doc/dut_fixture.md" ]; do \
		sleep 5; \
	done
	mkdir -p ../../output/.iflow
	cp ~/.iflow/settings.json ../../output/.iflow/settings.json
	sed -i "s/$(OPORT)\/mcp/$(APORT)\/mcp/" ../../output/.iflow/settings.json
	(sleep 10; tmux send-keys `ucagent --hook-message cagent_init`; sleep 1; tmux send-keys Enter)&
	cd ../../output && npx -y @iflow-ai/iflow-cli@latest -y && (echo true > exited.txt)
	sleep 30 # wait clean ready

iflow_batch:
	@$(MAKE) iflow_once # Adder
	@$(MAKE) iflow_once # Mux
	@$(MAKE) iflow_once # FSM

iflow_batch_auto_tmux:
	tmux kill-session -t my_batch_iflow_session_$(APORT) || true
	tmux new-session -d -s my_batch_iflow_session_$(APORT)
	tmux send-keys -t my_batch_iflow_session_$(APORT):0.0 "make mcp_batch" C-m
	tmux split-window -h -t my_batch_iflow_session_$(APORT):0.0
	tmux send-keys -t my_batch_iflow_session_$(APORT):0.1 "make iflow_batch" C-m
	tmux attach-session -t my_batch_iflow_session_$(APORT)
