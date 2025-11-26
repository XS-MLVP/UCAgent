# First try ../../ucagent.py then fallback to system installed ucagent
UCAGENT_PY := $(wildcard ../../ucagent.py)

ifdef UCAGENT_PY
CMD ?= python3 ../../ucagent.py
else
CMD ?= ucagent
endif

DUT ?= fish

default: mcp_tool

init:
	mkdir -p output
	rm output/* -rf

clean:
	rm output -rf

mcp_tool: init
	$(CMD) output/ $(DUT) -hm --tui --mcp-server-no-file-tools --no-embed-tools -app `pwd` -et my_tools.MyCustomTool

.PHONY: init clean