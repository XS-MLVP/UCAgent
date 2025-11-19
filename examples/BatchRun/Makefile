

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


mcp_batch: init
	make -C ../../ clean
	make -C ../../ mcp_Adder ARGS="-eoc"
	cp -r ../../output output/Adder
	@while [ ! -f "../../output/exited.txt" ]; do \
		sleep 5; \
	done
	make -C ../../ clean
	make -C ../../ mcp_Mux ARGS="-eoc"
	cp -r ../../output output/Mux
	@while [ ! -f "../../output/exited.txt" ]; do \
		sleep 5; \
	done
	make -C ../../ clean
	make -C ../../ mcp_FSM ARGS="-eoc"
	cp -r ../../output output/FSM


iflow_batch:
	#  iflow 通过 -i 参数传递初始 prompt 有bug，等待iflow修复
	#  替代方案：通过 bash 间接传递
	@while [ ! -f "../../output/Guide_Doc/dut_fixture.md" ]; do \
		sleep 5; \
	done
	(sleep 10; tmux send-keys -t 0 `ucagent --hook-message cagent_init`; sleep 1; tmux send-keys -t 0 Enter)&
	cd ../../output && npx -y @iflow-ai/iflow-cli@latest -y && (echo true > exited.txt)
	sleep 30 # wait clean ready
	@while [ ! -f "../../output/Guide_Doc/dut_fixture.md" ]; do \
		sleep 5; \
	done
	(sleep 10; tmux send-keys -t 0 `ucagent --hook-message cagent_init`; sleep 1; tmux send-keys -t 0 Enter)&
	cd ../../output && npx -y @iflow-ai/iflow-cli@latest -y && (echo true > exited.txt)
	sleep 30 # wait clean ready
	@while [ ! -f "../../output/Guide_Doc/dut_fixture.md" ]; do \
		sleep 5; \
	done
	(sleep 10; tmux send-keys -t 0 `ucagent --hook-message cagent_init`; sleep 1; tmux send-keys -t 0 Enter)&
	cd ../../output && npx -y @iflow-ai/iflow-cli@latest -y && (echo true > exited.txt)
