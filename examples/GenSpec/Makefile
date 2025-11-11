

CMD ?= python3 ../../ucagent.py

clean:
	rm ./output -rf

init: clean
	mkdir output
	cp -r DCache output/

spec:
	$(CMD) output/ DCache --config ./genspec.yaml -hm --tui -s --no-embed-tools -l $(ARGS)

spec_mcp:
	$(CMD) output/ DCache --config ./genspec.yaml -hm --tui --mcp-server-no-file-tools --no-embed-tools $(ARGS)

