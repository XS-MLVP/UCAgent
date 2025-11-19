
clean:
	make -C ../../ clean


api_mul: clean
	tmux kill-session -t my_multi_api_session || true
	tmux new-session -d -s my_multi_api_session
	tmux send-keys -t my_multi_api_session:0.0 ". ~/.IFLOW_env;make -C ../../ test_Adder ARGS='--no-embed-tools' CWD=output/A" C-m
	tmux split-window -h -t my_multi_api_session:0.0
	tmux send-keys -t my_multi_api_session:0.1 "slee 10; . ~/.IFLOW_env;make -C ../../ test_Mux ARGS='--no-embed-tools' CWD=output/B" C-m
	tmux attach-session -t my_multi_api_session

