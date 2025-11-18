

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
	make -C ../../ clean
	make -C ../../ mcp_Mux ARGS="-eoc"
	cp -r ../../output output/Mux
	make -C ../../ clean
	make -C ../../ mcp_FSM ARGS="-eoc"
	cp -r ../../output output/FSM


iflow_batch:
	# sleep 100 # 等待 output 目录准备好，生产环境建议用更可靠的方式确认，例如判断特定文件是否存在
	#  通过 -i 参数传递初始 prompt
	cd ../../output && npx -y @iflow-ai/iflow-cli@latest -y -i `ucagent --hook-message 'cagent_init'`
	sleep 100
	cd ../../output && npx -y @iflow-ai/iflow-cli@latest -y -i `ucagent --hook-message 'cagent_init'`
	sleep 100
	cd ../../output && npx -y @iflow-ai/iflow-cli@latest -y -i `ucagent --hook-message 'cagent_init'`
