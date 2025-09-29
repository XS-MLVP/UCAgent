
all: clean test

init:
	pip3 install -r requirements.txt

dut:
	rm output -rf
	mkdir -p output
	cp -r examples output/

reset_%:
	rm output/unity_test -rf  | true
	cp examples/$*/*.md output/$*/ | true
	cp examples/$*/*.py output/$*/ | true
	cp vagent/doc/* output/ -r  | true

init_%:
	rm output/examples/$* -rf
	@if [ ! -d output/$* ]; then \
		option_fs=""; \
		if [ -f examples/$*/filelist.txt ]; then \
			option_fs="--fs examples/$*/filelist.txt"; \
		fi; \
		if [ -f examples/$*/$*.v ]; then \
			picker export examples/$*/$*.v --rw 1 --sname $* --tdir output/ -c -w output/$*/$*.fst $$option_fs; \
		fi; \
	fi
	cp examples/$*/*.md output/$*/  | true
	cp examples/$*/*.sv output/$*/  | true
	cp examples/$*/*.v output/$*/  | true
	cp examples/$*/*.py output/$*/  | true
	cp examples/$*/*.scala output/$*/  | true
	cp vagent/doc/* output/ -r  | true

test_%: init_%
	python3 ucagent.py output/ $* --config config.yaml -s -hm --tui -l ${ARGS}

mcp_%: init_%
	python3 ucagent.py output/ $* --config config.yaml -s -hm --tui --mcp-server-no-file-tools --no-embed-tools ${ARGS}

mcp_all_tools_%: init_%
	python3 ucagent.py output/ $* --config config.yaml -s -hm --tui --mcp-server ${ARGS}

clean:
	rm -rf output
	rm -rf .pytest_cache
	rm -rf UCAgent.egg-info
	rm -rf build
	rm -rf dist
	find ./ -name '*.dat'|xargs rm -f
	find ./ -name '*.vcd'|xargs rm -f
	find ./ -name '*.fst'|xargs rm -f
	find ./ -name __pycache__|xargs rm -rf

clean_test:
	rm -rf output/unity_test

continue:
	python3 ucagent.py output/ ${DUT} --config config.yaml ${ARGS}
