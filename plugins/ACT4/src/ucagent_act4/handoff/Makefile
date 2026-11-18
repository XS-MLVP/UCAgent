# Recipient entry points for complete ACT programs; testcase boundaries stay unchanged.
PYTHON ?= python3
JOBS ?= 1
TIMEOUT ?= 3600
CYCLES ?= 20000000
TEST ?=
EMU ?=
LOCAL ?= 0
MODIFIED ?= 0
export JOBS TIMEOUT CYCLES TEST EMU LOCAL MODIFIED
.PHONY: all build run list verify doctor setup disass
all: build
build disass:
	@set -- build --jobs "$$JOBS" --timeout "$$TIMEOUT"; \
	if [ -n "$$TEST" ]; then set -- "$$@" --test "$$TEST"; fi; \
	if [ "$$MODIFIED" = 1 ]; then set -- "$$@" --modified; fi; \
	$(PYTHON) handoff.py "$$@"
run:
	@set -- run --emu "$$EMU" --cycles "$$CYCLES" --timeout "$$TIMEOUT"; \
	if [ -n "$$TEST" ]; then set -- "$$@" --test "$$TEST"; fi; \
	if [ "$$LOCAL" = 1 ]; then set -- "$$@" --local; fi; \
	$(PYTHON) handoff.py "$$@"
list verify:
	@$(PYTHON) handoff.py $@
doctor:
	@set -- doctor --timeout "$$TIMEOUT"; \
	if [ -n "$$EMU" ]; then set -- "$$@" --emu "$$EMU"; fi; \
	$(PYTHON) handoff.py "$$@"
setup:
	@$(PYTHON) handoff.py setup --timeout "$$TIMEOUT"
