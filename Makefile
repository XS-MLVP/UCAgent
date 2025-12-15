
# Current Workspace Dir
CWD ?= output
CFG ?= config.yaml

all: clean test

init:
	pip3 install -r requirements.txt

reset_%:
	rm $(CWD)/unity_test -rf  || true

init_%:
	mkdir -p $(CWD)/$*_RTL
	cp examples/$*/*.v $(CWD)/$*_RTL/ || true
	cp examples/$*/*.sv $(CWD)/$*_RTL/ || true
	cp examples/$*/*.vh $(CWD)/$*_RTL/ || true
	cp examples/$*/*.scala $(CWD)/$*_RTL/ || true
	cp examples/$*/filelist.txt $(CWD)/$*_RTL/ || true
	@if [ ! -d $(CWD)/$* ]; then \
		option_fs=""; \
		if [ -f $(CWD)/$*_RTL/filelist.txt ]; then \
			option_fs="--fs $(CWD)/$*_RTL/filelist.txt"; \
		fi; \
		if [ -f $(CWD)/$*_RTL/$*.v ]; then \
			picker export $(CWD)/$*_RTL/$*.v --rw 1 --sname $* --tdir $(CWD)/ -c -w $(CWD)/$*/$*.fst $$option_fs; \
		elif [ -f $(CWD)/$*_RTL/$*.sv ]; then \
			picker export $(CWD)/$*_RTL/$*.sv --rw 1 --sname $* --tdir $(CWD)/ -c -w $(CWD)/$*/$*.fst $$option_fs; \
		fi; \
	fi
	cp examples/$*/*.md $(CWD)/$*/  || true
	cp examples/$*/*.py $(CWD)/$*/  || true

test_%: init_%
	python3 ucagent.py $(CWD)/ $* --config $(CFG) -s -hm --tui -l ${ARGS}

mcp_%: init_%
	python3 ucagent.py $(CWD)/ $* --config $(CFG) -s -hm --tui --mcp-server-no-file-tools --no-embed-tools ${ARGS}

mcp_all_tools_%: init_%
	python3 ucagent.py $(CWD)/ $* --config $(CFG) -s -hm --tui --mcp-server ${ARGS}

clean:
	rm -rf $(CWD)
	rm -rf .pytest_cache
	rm -rf UCAgent.egg-info
	rm -rf build
	rm -rf dist
	find ./ -name '*.dat'||xargs rm -f
	find ./ -name '*.vcd'||xargs rm -f
	find ./ -name '*.fst'||xargs rm -f
	find ./ -name __pycache__||xargs rm -rf

clean_test:
	rm -rf $(CWD)/unity_test

continue:
	python3 ucagent.py $(CWD)/ ${DUT} --config config.yaml ${ARGS}

# Include docs Makefile
-include docs/Makefile
