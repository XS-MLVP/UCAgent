# Makefile for Formal Verification example

# Current Workspace Dir
CWD ?= output/workspace_$*

# First try ../../ucagent.py then fallback to system installed ucagent
UCAGENT_PY := $(wildcard ../../ucagent.py)

ifdef UCAGENT_PY
CMD ?= python3 ../../ucagent.py
else
CMD ?= ucagent
endif

clean:
	rm ./output -rf

init_%: 
	mkdir -p $(CWD)
	cp -r rtls/$* $(CWD)/

test_%: init_%
	$(CMD) $(CWD)/ $* --config ./formal.yaml -s -hm --tui --guid-doc-path ./FormalDoc/ --output formal_test ${ARGS}

mcp_%: init_%
	$(CMD) $(CWD)/ $* --config ./formal.yaml -s -hm --tui --mcp-server-no-file-tools --guid-doc-path ./FormalDoc/ --output formal_test --mcp-server-port 5000 --master 127.0.0.1 --export-cmd-api --use-skill --log ${ARGS}
