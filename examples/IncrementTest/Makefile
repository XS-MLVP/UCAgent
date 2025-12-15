# First try ../../ucagent.py then fallback to system installed ucagent
UCAGENT_PY := $(wildcard ../../ucagent.py)
CONT ?= false
ifdef UCAGENT_PY
CMD ?= python3 ../../ucagent.py
else
CMD ?= ucagent
endif


init_workspace:
	@if [ ! -d ../../output ]; then \
		echo "Error: Please complete Adder verification first."; \
		exit 1; \
	fi
	@if [ $(CONT) = false ]; then \
		echo "clean output"; \
		rm output -rf || true; \
		cp -r ../../output output; \
		rm output/.ucagent_info.json -f || true; \
	fi

# default init with mcp server no file tools
init: init_workspace
	$(CMD) output/ Adder --config inc.yaml -hm --tui --mcp-server-no-file-tools --no-embed-tools $(ARGS)


init_test: init_workspace
	$(CMD) output/ Adder --config inc.yaml -s -hm --tui --no-embed-tools $(ARGS)


diff:
	rm output/Adder -rf || true
	cat Adder_new.v > output/Adder_RTL/Adder.v
	picker export output/Adder_RTL/Adder.v --rw 1 --sname Adder --tdir output/ -c -w output/Adder/Adder.fst
	cp Adder_new_README.md output/Adder/README.md || true
