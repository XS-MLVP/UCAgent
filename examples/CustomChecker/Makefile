# First try ../../ucagent.py then fallback to system installed ucagent
UCAGENT_PY := $(wildcard ../../ucagent.py)

ifdef UCAGENT_PY
CMD ?= python3 ../../ucagent.py
else
CMD ?= ucagent
endif

DUT ?= fish

default: mcp_joke

init:
	mkdir -p output
	rm output/* -rf

clean:
	rm output -rf

mcp_joke: init
	$(CMD) output/ $(DUT) --config ./joke.yaml -hm --tui --mcp-server-no-file-tools --no-embed-tools -app `pwd`

.PHONY: init clean