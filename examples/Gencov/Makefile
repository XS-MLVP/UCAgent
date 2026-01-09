# Makefile for Gencov example

# First try ../../ucagent.py then fallback to system installed ucagent
UCAGENT_PY := $(wildcard ../../ucagent.py)

ifdef UCAGENT_PY
CMD ?= python3 ../../ucagent.py
else
CMD ?= ucagent
endif

# Output directory (project root by default)
OUT_DIR ?= ../../output
OUT_DIR_ABS := $(abspath $(OUT_DIR))

clean:
	rm -rf $(OUT_DIR_ABS)

init_%: clean
	mkdir -p $(OUT_DIR_ABS)
	cp -r $* $(OUT_DIR_ABS)/
	cp -r ../../ucagent/lang/zh/doc/Guide_Doc $(OUT_DIR_ABS)/
	mkdir -p $(OUT_DIR_ABS)/$*/gencov/skeletons
	cp -r GenCov/skeletons/* $(OUT_DIR_ABS)/$*/gencov/skeletons/
	cp GenCov/check_tp_consistency.py $(OUT_DIR_ABS)/$*/gencov/
	@hvp_src=$$(ls $*/spec/*.hvp $*/hvp/*.hvp 2>/dev/null | head -n 1); \
	if [ -n "$$hvp_src" ]; then \
		mkdir -p $(OUT_DIR_ABS)/$*/spec; \
		cp -f "$$hvp_src" "$(OUT_DIR_ABS)/$*/spec/$*_verification_plan.hvp"; \
	else \
		echo "WARNING: no .hvp found under $*/spec or $*/hvp"; \
	fi

gencov_%:
	$(CMD) $(OUT_DIR_ABS)/ $* --config ./GenCov/gencov.yaml -hm --tui -s --no-embed-tools -l \
	$(ARGS)

gencov_mcp_%:
	$(CMD) $(OUT_DIR_ABS)/ $* --config ./GenCov/gencov.yaml -hm --tui --mcp-server-no-file-tools --no-embed-tools \
	$(ARGS)
