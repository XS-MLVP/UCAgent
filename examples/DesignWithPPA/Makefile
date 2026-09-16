ifeq ($(origin PYTHON), undefined)
PYTHON := $(shell command -v python 2>/dev/null || command -v python3)
endif
ifeq ($(origin PYTHON), default)
PYTHON := $(shell command -v python 2>/dev/null || command -v python3)
endif
PYTHON ?= python3
CASE ?= LowPrecisionMatMul2x2
CASE_SOURCE_ROOT ?= cases
WORKSPACE_ROOT ?= output
VERILOG_WORKSPACE ?= $(WORKSPACE_ROOT)/workspace_$(CASE)_verilog
CHISEL_WORKSPACE ?= $(WORKSPACE_ROOT)/workspace_$(CASE)_chisel
REPO_WORKSPACE ?= $(WORKSPACE_ROOT)/workspace_$(CASE)_repo
DEMO_REPO_SOURCE ?= $(WORKSPACE_ROOT)/repo_demo_source
CASE_LIBRARY_PATHS ?= $(if $(wildcard $(CASE_SOURCE_ROOT)/$(CASE)/lib),["$(CASE)/lib"],[])
OUTPUT ?= design
DASHBOARD_WORKSPACE ?= $(VERILOG_WORKSPACE)
PLUGIN ?= $(CURDIR)
BACKEND ?= opencode
PORT ?= 8000
DF_ARGS ?= -hm --tui --override call_time_out=36000 --override cmd_timeout=36000
ARGS ?=
CHISEL_JAVA_HOME ?= $(HOME)/.local/share/ucagent-toolchains/jdk-17
MILL ?= mill
POSIX_SHELL ?= sh

MAKEFILE_PATH := $(abspath $(lastword $(MAKEFILE_LIST)))
PLUGIN_ROOT := $(patsubst %/,%,$(dir $(MAKEFILE_PATH)))
REPO_ROOT := $(abspath $(PLUGIN_ROOT)/../..)
SOURCE_CLI := $(REPO_ROOT)/ucagent.py
SOURCE_PACKAGE := $(REPO_ROOT)/ucagent/__init__.py
UCAGENT := $(if $(and $(wildcard $(SOURCE_CLI)),$(wildcard $(SOURCE_PACKAGE))),$(PYTHON) $(SOURCE_CLI),ucagent)
LOCAL_PYTHONPATH := $(REPO_ROOT):$(CURDIR)/src
PYTHON_BIN_DIR := $(dir $(PYTHON))

.DEFAULT_GOAL := help
.PHONY: help validate test check-deps prepare-verilog-case prepare-chisel-case prepare-repo-case prepare-repo-demo-source run run-chisel run-repo chisel-toolchain package dashboard clean

help:
	@echo "DesignWithPPA quick commands"
	@echo "  make validate   Validate the local plugin descriptor and dependencies"
	@echo "  make test       Run the plugin regression suite"
	@echo "  make check-deps Check external workflow tools (picker, yosys, OpenSTA, backend)"
	@echo "  make run        Run CASE with the unit-design-tdd workflow"
	@echo "  make run-chisel Run CASE with the pinned Chisel 7 workflow backend"
	@echo "  make run-repo   Develop a unit using SOURCE_PATH as read-only source dependencies"
	@echo "  make prepare-repo-demo-source  Create the demo Git source for CASE=repo_byte_increment"
	@echo "  make chisel-toolchain  Check JDK 17+ and Mill 0.4.2"
	@echo "  make package    Build the plugin sdist and wheel"
	@echo "  make dashboard  Serve WORKSPACE for the generated HTML dashboard"
	@echo "  make clean      Remove the plugin's declared generated directories and file types"
	@echo ""
	@echo "Verilog workspace: $(abspath $(VERILOG_WORKSPACE))"
	@echo "Chisel workspace:  $(abspath $(CHISEL_WORKSPACE))"
	@echo "Overrides: CASE=... CASE_SOURCE_ROOT=... WORKSPACE_ROOT=... VERILOG_WORKSPACE=... CHISEL_WORKSPACE=... CASE_LIBRARY_PATHS=... OUTPUT=... BACKEND=... ARGS='...' PORT=8000"

validate:
	$(UCAGENT) --validate-plugin "$(PLUGIN)"

test:
	PATH="$(PYTHON_BIN_DIR):$${PATH}" PYTHONPATH="$(LOCAL_PYTHONPATH):$${PYTHONPATH}" $(PYTHON) -m pytest -q tests

# Mirror the plugin's CommandRequirement checks so a workflow run fails fast
# with one labeled summary instead of dying in a later stage.
check-deps:
	@missing=0; \
	check_cmd() { \
		label="$$1"; shift; \
		for name in $$*; do \
			if command -v "$$name" >/dev/null 2>&1; then \
				printf '  [ok]   %-24s %s\n' "$$label" "$$(command -v "$$name")"; \
				return 0; \
			fi; \
		done; \
		printf '  [miss] %s\n' "$$label"; \
		missing=1; \
	}; \
	echo "Checking external workflow dependencies:"; \
	check_cmd "Picker (picker)" picker; \
	if command -v picker >/dev/null 2>&1 && ! picker export --help >/dev/null 2>&1; then \
		echo '  [miss] picker subcommand: export'; \
		missing=1; \
	fi; \
	check_cmd "Yosys (yosys)" yosys; \
	if command -v yosys >/dev/null 2>&1; then printf '         %s\n' "$$(yosys -V 2>&1)"; fi; \
	check_cmd "OpenSTA (sta/opensta)" sta opensta; \
	check_cmd "Backend ($(BACKEND))" $(BACKEND); \
	if test "$$missing" -ne 0; then \
		echo "Missing dependencies above; see the dependency installation section in README.md for install commands." >&2; \
		exit 1; \
	fi

prepare-verilog-case:
	@test -f "$(CASE_SOURCE_ROOT)/$(CASE)/README.md" || { echo "Missing case README: $(CASE_SOURCE_ROOT)/$(CASE)/README.md" >&2; exit 1; }
	@test -d "$(CASE_SOURCE_ROOT)/$(CASE)/spec" || { echo "Missing case specs: $(CASE_SOURCE_ROOT)/$(CASE)/spec" >&2; exit 1; }
	@if test -f "$(VERILOG_WORKSPACE)/$(CASE)/README.md" && test -d "$(VERILOG_WORKSPACE)/$(CASE)/spec"; then \
		echo "Reusing existing read-only Verilog case snapshot: $(VERILOG_WORKSPACE)/$(CASE)"; \
	else \
		mkdir -p "$(VERILOG_WORKSPACE)/$(CASE)" && cp -R "$(CASE_SOURCE_ROOT)/$(CASE)/." "$(VERILOG_WORKSPACE)/$(CASE)/"; \
	fi

prepare-chisel-case:
	@test -f "$(CASE_SOURCE_ROOT)/$(CASE)/README.md" || { echo "Missing case README: $(CASE_SOURCE_ROOT)/$(CASE)/README.md" >&2; exit 1; }
	@test -d "$(CASE_SOURCE_ROOT)/$(CASE)/spec" || { echo "Missing case specs: $(CASE_SOURCE_ROOT)/$(CASE)/spec" >&2; exit 1; }
	@if test -f "$(CHISEL_WORKSPACE)/$(CASE)/README.md" && test -d "$(CHISEL_WORKSPACE)/$(CASE)/spec"; then \
		echo "Reusing existing read-only Chisel case snapshot: $(CHISEL_WORKSPACE)/$(CASE)"; \
	else \
		mkdir -p "$(CHISEL_WORKSPACE)/$(CASE)" && cp -R "$(CASE_SOURCE_ROOT)/$(CASE)/." "$(CHISEL_WORKSPACE)/$(CASE)/"; \
	fi

prepare-repo-case:
	@test -n "$(SOURCE_PATH)" || { echo "Set SOURCE_PATH to the source Git repository root." >&2; exit 1; }
	@test -f "$(CASE_SOURCE_ROOT)/$(CASE)/README.md" || { echo "Missing repository-module task README." >&2; exit 1; }
	@if ! test -f "$(REPO_WORKSPACE)/$(CASE)/README.md"; then \
		mkdir -p "$(REPO_WORKSPACE)/$(CASE)" && cp -R "$(CASE_SOURCE_ROOT)/$(CASE)/." "$(REPO_WORKSPACE)/$(CASE)/"; \
	fi

# Bootstrap the read-only source Git repository described by the
# repo_byte_increment case so the repo-module-tdd workflow can be exercised
# end to end without an external project checkout.
prepare-repo-demo-source:
	@if test -f "$(DEMO_REPO_SOURCE)/rtl/unit.v"; then \
		echo "Reusing demo source repository: $(DEMO_REPO_SOURCE)"; \
	else \
		mkdir -p "$(DEMO_REPO_SOURCE)/rtl"; \
		printf '%s\n' "// Increment one byte." > "$(DEMO_REPO_SOURCE)/rtl/unit.v"; \
		printf '%s\n' "module Unit(input [7:0] a, output [7:0] y); assign y = a + 8'd1; endmodule" >> "$(DEMO_REPO_SOURCE)/rtl/unit.v"; \
		printf '\n%s\n\n%s\n' "# Demo Source" "Independent byte-increment module fixture for the repo_byte_increment case." > "$(DEMO_REPO_SOURCE)/README.md"; \
		git -c init.defaultBranch=main -C "$(DEMO_REPO_SOURCE)" init -q; \
		git -C "$(DEMO_REPO_SOURCE)" -c user.name="DesignWithPPA Demo" -c user.email="demo@example.invalid" add .; \
		git -C "$(DEMO_REPO_SOURCE)" -c user.name="DesignWithPPA Demo" -c user.email="demo@example.invalid" commit -qm "Initial byte-increment unit"; \
		echo "Created demo source repository: $(DEMO_REPO_SOURCE)"; \
	fi

run-repo: validate check-deps prepare-repo-case
	SOURCE_PATH="$(SOURCE_PATH)" PATH="$(PYTHON_BIN_DIR):$${PATH}" $(UCAGENT) "$(REPO_WORKSPACE)" "$(CASE)" \
		--plugin "$(PLUGIN)" \
		--plugin-workflow design-with-ppa:repo-module-tdd \
		--backend "$(BACKEND)" --mcp-server-no-file-tools --output "$(OUTPUT)" \
		--stream-output --loop $(DF_ARGS) $(ARGS)

run: validate check-deps prepare-verilog-case
	PATH="$(PYTHON_BIN_DIR):$${PATH}" $(UCAGENT) "$(VERILOG_WORKSPACE)" "$(CASE)" \
		--plugin "$(PLUGIN)" \
		--plugin-workflow design-with-ppa:unit-design-tdd \
		--backend "$(BACKEND)" \
		--mcp-server-no-file-tools \
		--output "$(OUTPUT)" \
		--override 'design_with_ppa.rtl.library_paths=$(CASE_LIBRARY_PATHS)' \
		--stream-output \
		--loop $(DF_ARGS) $(ARGS)

chisel-toolchain:
	@test -x "$(CHISEL_JAVA_HOME)/bin/java" || { echo "Set CHISEL_JAVA_HOME to a JDK 17+ home." >&2; exit 1; }
	@command -v "$(MILL)" >/dev/null 2>&1 || { echo "Mill 0.4.2 is required in PATH." >&2; exit 1; }
	@command -v "$(POSIX_SHELL)" >/dev/null 2>&1 || { echo "A POSIX shell is required to launch Mill 0.4.2." >&2; exit 1; }
	@JAVA_HOME="$(CHISEL_JAVA_HOME)" "$(CHISEL_JAVA_HOME)/bin/java" -version
	@mill_bin="$$(command -v "$(MILL)")"; toolchain_tmp="$$(mktemp -d "$${TMPDIR:-/tmp}/ucagent-chisel-toolchain.XXXXXX")"; trap 'rm -rf "$$toolchain_tmp"' EXIT INT TERM; cd "$$toolchain_tmp" && JAVA_HOME="$(CHISEL_JAVA_HOME)" "$(POSIX_SHELL)" "$$mill_bin" -i version | grep -x '0.4.2'

run-chisel: validate check-deps chisel-toolchain prepare-chisel-case
	PATH="$(PYTHON_BIN_DIR):$${PATH}" JAVA_HOME="$(CHISEL_JAVA_HOME)" $(UCAGENT) "$(CHISEL_WORKSPACE)" "$(CASE)" \
		--plugin "$(PLUGIN)" \
		--plugin-workflow design-with-ppa:unit-design-tdd \
		--backend "$(BACKEND)" \
		--mcp-server-no-file-tools \
		--output "$(OUTPUT)" \
		--override 'design_with_ppa.rtl.library_paths=$(CASE_LIBRARY_PATHS)' \
		--override design_with_ppa.rtl.language=chisel \
		--override 'design_with_ppa.rtl.source_glob=$(OUTPUT)/rtl/*.scala' \
		--override design_with_ppa.rtl.source_template=chisel-7 \
		--stream-output \
		--loop $(DF_ARGS) $(ARGS)

package:
	@if $(PYTHON) -c "import build" >/dev/null 2>&1; then \
		$(PYTHON) -m build .; \
	elif command -v uv >/dev/null 2>&1; then \
		uv build .; \
	else \
		echo "Install the Python 'build' package or uv to build distributions." >&2; \
		exit 1; \
	fi

dashboard:
	@echo "Serving $(abspath $(DASHBOARD_WORKSPACE)) at http://127.0.0.1:$(PORT)/$(OUTPUT)/$(CASE)_ppa_dashboard.html"
	$(PYTHON) -m http.server "$(PORT)" --directory "$(DASHBOARD_WORKSPACE)"

clean:
	@test -f "$(CURDIR)/ucagent-plugin.toml" || { echo "Refusing to clean outside the DesignWithPPA plugin root." >&2; exit 1; }
	@for clean_target in "$(CURDIR)/output" "$(CURDIR)/dist" "$(CURDIR)/build" \
		"$(CURDIR)/.pytest_cache" "$(CURDIR)/.mypy_cache" "$(CURDIR)/.ruff_cache" "$(CURDIR)/htmlcov"; do \
		if test -e "$$clean_target"; then chmod -R u+w "$$clean_target"; fi; \
	done
	rm -rf -- "$(CURDIR)/output" "$(CURDIR)/dist" "$(CURDIR)/build" \
		"$(CURDIR)/.pytest_cache" "$(CURDIR)/.mypy_cache" \
		"$(CURDIR)/.ruff_cache" "$(CURDIR)/htmlcov"
	find "$(CURDIR)" -type d \( -name '__pycache__' -o -name '*.egg-info' \) -prune -exec chmod -R u+w {} \;
	find "$(CURDIR)" -type d \( -name '__pycache__' -o -name '*.egg-info' \) -prune -exec rm -rf -- {} +
	find "$(CURDIR)" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.coverage' -o -name '.coverage.*' \) -exec chmod u+w {} \;
	find "$(CURDIR)" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.coverage' -o -name '.coverage.*' \) -delete
	rm -rf log
