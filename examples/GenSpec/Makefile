# Makefile for GenSpec example

# First try ../../ucagent.py then fallback to system installed ucagent
UCAGENT_PY := $(wildcard ../../ucagent.py)

ifdef UCAGENT_PY
CMD ?= python3 ../../ucagent.py
else
CMD ?= ucagent
endif

clean:
	rm ./output -rf

init_%: clean
	mkdir output
	cp -r $* output/

spec_%:
	$(CMD) output/ $* --config ./genspec.yaml -hm --tui -s --no-embed-tools -l --guid-doc-path ./SpecDoc/dut_spec_template.md $(ARGS)

spec_mcp_%:
	$(CMD) output/ $* --config ./genspec.yaml -hm --tui --mcp-server-no-file-tools --no-embed-tools --guid-doc-path ./SpecDoc/dut_spec_template.md $(ARGS)
