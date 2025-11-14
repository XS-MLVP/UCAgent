all: clean test

init:
	pip3 install -r requirements.txt

reset_%:
	rm output/unity_test -rf  | true

init_%:
	mkdir -p output/$*_RTL
	cp examples/$*/*.v output/$*_RTL/ | true
	cp examples/$*/*.sv output/$*_RTL/ | true
	cp examples/$*/*.vh output/$*_RTL/ | true
	cp examples/$*/*.scala output/$*_RTL/ | true
	cp examples/$*/filelist.txt output/$*_RTL/ | true
	@if [ ! -d output/$* ]; then \
		option_fs=""; \
		if [ -f output/$*_RTL/filelist.txt ]; then \
			option_fs="--fs output/$*_RTL/filelist.txt"; \
		fi; \
		if [ -f output/$*_RTL/$*.v ]; then \
			picker export output/$*_RTL/$*.v --rw 1 --sname $* --tdir output/ -c -w output/$*/$*.fst $$option_fs; \
		elif [ -f output/$*_RTL/$*.sv ]; then \
			picker export output/$*_RTL/$*.sv --rw 1 --sname $* --tdir output/ -c -w output/$*/$*.fst $$option_fs; \
		fi; \
	fi
	cp examples/$*/*.md output/$*/  | true
	cp examples/$*/*.py output/$*/  | true

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

# Include docs Makefile
-include docs/Makefile
