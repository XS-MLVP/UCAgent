# Makefile for Formal Verification example

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
	mkdir -p output
	cp -r rtls/$* output/

mcp_%:  init_%
	$(CMD) output/ $* --config ./formal.yaml -s -hm --legacy-ui --mcp-server-no-file-tools --no-embed-tools --guid-doc-path ./FormalDoc/ --output unity_tests --mcp-server-port 5000 ${ARGS}

co_%:
	$(CMD) output/ $* --config ./formal.yaml -s -hm --legacy-ui --mcp-server-no-file-tools --no-embed-tools --guid-doc-path ./FormalDoc/ --output unity_tests --mcp-server-port 5000 ${ARGS}


run_formal_%:
	cd output/$* && bash scripts/run_formal.sh
