# UCAgent development commands and verification workflow entry points.

# Shared executables
PYTHON ?= python3
NODE ?= node
UCAGENT_PY := $(wildcard ucagent.py)
ifdef UCAGENT_PY
CMD ?= python3 ucagent.py
else
CMD ?= ucagent
endif

## Development
all: clean test

.PHONY: help unittest
help: ## Show grouped targets, common variables, and examples
	@awk 'BEGIN { FS = ":.*## "; print "Usage: make <target> [VARIABLE=value ...]"; \
		print "Replace % with the DUT name, e.g. test_Adder." } \
		/^## / { printf "\n%s\n", substr($$0, 4) } \
		/^[[:alnum:]_.%-]+:.*## / { printf "  %-24s %s\n", $$1, $$2 } \
		END { print "\nCommon variables: CWD, SRC, SIM, CFG, ARGS, BBV, MAX_SUBAGENTS, MASTER_IP, PATH_PERSISTENT"; \
		print "Simulators: verilator (default), gsim, vcs, uvs"; \
		print "\nExamples:"; \
		print "  make test_Adder SIM=vcs"; \
		print "  make test_multi_Adder MAX_SUBAGENTS=2"; \
		print "  make mcp_multi_Adder MAX_SUBAGENTS=2"; \
		print "  make mcp_Adder ARGS=\"--loop --backend=codex\""; \
		print "  make as_master_persist PATH_PERSISTENT=/tmp/ucagent_master" }' $(MAKEFILE_LIST)

unittest: ## Run the Python and JavaScript test suites
	$(PYTHON) -m pytest -q tests
	$(NODE) --test tests/test_*.js

init: ## Install project dependencies
	pip3 install -r requirements.txt

clean: ## Remove caches, build artifacts, waveforms, and output directories
	rm -rf .pytest_cache
	rm -rf log
	rm -rf UCAgent.egg-info
	rm -rf build
	rm -rf dist
	rm -rf site
	find ./ -name '*.dat'|xargs rm -f
	find ./ -name '*.vcd'|xargs rm -f
	find ./ -name '*.fst'|xargs rm -f
	find ./ -name __pycache__|xargs rm -rf
	find ./ -name output|xargs rm -rf

# Workflow rules (keep the default target above all includes).
include make/workspace.mk
include make/master.mk
-include docs/Makefile
include make/formal.mk
