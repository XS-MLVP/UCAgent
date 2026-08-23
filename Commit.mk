# Safe commit helper for the Workflow Builder code and its published documentation.

SHELL := /bin/bash
.DEFAULT_GOAL := help

THIS_MAKEFILE := $(abspath $(lastword $(MAKEFILE_LIST)))
REPO_ROOT := $(shell git -C $(dir $(THIS_MAKEFILE)) rev-parse --show-toplevel 2>/dev/null)
GIT := git -c core.quotePath=false -C "$(REPO_ROOT)"

EXPECTED_BRANCH ?= dwl
WORKFLOW_BUILDER_PATH ?= examples/workflow_builder
WORKFLOW_BUILDER_DOCS_PATH ?= docs/content/extension/workflow_builder
DOCS_NAV_PATH ?= docs/mkdocs.yml
DOCS_PANDOC_PATH ?= docs/pandoc.mk
COMMIT_MAKEFILE_PATH ?= Commit.mk
MAX_FILE_MB ?= 10
MSG ?=

ALLOWED_PATHS := $(WORKFLOW_BUILDER_PATH) $(WORKFLOW_BUILDER_DOCS_PATH) $(DOCS_NAV_PATH) $(DOCS_PANDOC_PATH) $(COMMIT_MAKEFILE_PATH)

# Negative pathspecs prevent runtime and AI-assistant files from entering the
# index in the first place. The post-stage purge and verify rules below remain
# as a second line of defense for tracked files and future pattern changes.
STAGE_PATHS := \
	':(top)$(WORKFLOW_BUILDER_PATH)' \
	':(top)$(WORKFLOW_BUILDER_DOCS_PATH)' \
	':(top)$(DOCS_NAV_PATH)' \
	':(top)$(DOCS_PANDOC_PATH)' \
	':(top)$(COMMIT_MAKEFILE_PATH)' \
	':(top,exclude)$(WORKFLOW_BUILDER_PATH)/workspace' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/workspace/**' \
	':(top,exclude)$(WORKFLOW_BUILDER_PATH)/tmp' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/tmp/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.ucagent' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.ucagent/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.workflow_builder' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.workflow_builder/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/node_modules' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/node_modules/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.claude*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.claude*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.qwen*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.qwen*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.codex*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.codex*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.gemini*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.gemini*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.cursor*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.cursor*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.aider*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.aider*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.continue*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.continue*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.windsurf*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.windsurf*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.roo*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.roo*/**' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.kilocode*' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.kilocode*/**' \
	':(top,exclude,icase,glob)$(WORKFLOW_BUILDER_PATH)/**/claude*.md' \
	':(top,exclude,icase,glob)$(WORKFLOW_BUILDER_PATH)/**/agents*.md' \
	':(top,exclude,icase,glob)$(WORKFLOW_BUILDER_PATH)/**/gemini*.md' \
	':(top,exclude,icase,glob)$(WORKFLOW_BUILDER_PATH)/**/copilot-instructions.md' \
	':(top,exclude,glob)$(WORKFLOW_BUILDER_PATH)/**/.mcp.json'

# This expression is evaluated against repository-relative staged paths.
FORBIDDEN_RE := (^|/)(\.ucagent|\.workflow_builder|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.cache|workspace|tmp|node_modules)(/|$$)|(^|/)\.(claude|qwen|codex|gemini|cursor|aider|continue|windsurf|roo|kilocode)[^/]*(/|$$)|(^|/)(claude|agents|gemini)([._-][^/]*)?\.md$$|(^|/)copilot-instructions\.md$$|(^|/)\.mcp\.json$$|\.(py[co]|log|tmp|swp)$$|(^|/)\.DS_Store$$

.PHONY: help repo-check branch status excluded preview stage verify review commit unstage clean-cache

help:
	@printf '%s\n' \
	  'Workflow Builder safe commit helper' \
	  '' \
	  '  make -f Commit.mk status' \
	  '      Show scoped working-tree and staged changes.' \
	  '  make -f Commit.mk excluded' \
	  '      List local cache, runtime, and AI-assistant files that will not be staged.' \
	  '  make -f Commit.mk preview' \
	  '      Dry-run the exact safe staging pathspec.' \
	  '  make -f Commit.mk stage' \
	  '      Stage Workflow Builder code, published extension docs, navigation, and this helper.' \
	  '  make -f Commit.mk verify' \
	  '      Reject wrong scope, forbidden names, whitespace errors, and large files.' \
	  '  make -f Commit.mk review' \
	  '      Verify and display the staged summary and diff.' \
	  '  make -f Commit.mk commit MSG="workflow_builder: describe change"' \
	  '      Stage, verify, and commit on the expected branch.' \
	  '  make -f Commit.mk unstage' \
	  '      Unstage this helper scope without changing working-tree files.' \
	  '' \
	  'Overrides: EXPECTED_BRANCH=dwl MAX_FILE_MB=10 WORKFLOW_BUILDER_PATH=examples/workflow_builder'

repo-check:
	@test -n "$(REPO_ROOT)" || { echo 'Error: Commit.mk is not inside a Git repository.' >&2; exit 2; }
	@test -d "$(REPO_ROOT)/$(WORKFLOW_BUILDER_PATH)" || { \
		echo 'Error: missing $(WORKFLOW_BUILDER_PATH) below $(REPO_ROOT).' >&2; exit 2; \
	}
	@test -d "$(REPO_ROOT)/$(WORKFLOW_BUILDER_DOCS_PATH)" || { \
		echo 'Error: missing $(WORKFLOW_BUILDER_DOCS_PATH) below $(REPO_ROOT).' >&2; exit 2; \
	}
	@test -f "$(REPO_ROOT)/$(DOCS_NAV_PATH)" || { \
		echo 'Error: missing $(DOCS_NAV_PATH) below $(REPO_ROOT).' >&2; exit 2; \
	}
	@test -f "$(REPO_ROOT)/$(DOCS_PANDOC_PATH)" || { \
		echo 'Error: missing $(DOCS_PANDOC_PATH) below $(REPO_ROOT).' >&2; exit 2; \
	}

branch: repo-check
	@current="$$($(GIT) branch --show-current)"; \
	if [[ "$$current" != "$(EXPECTED_BRANCH)" ]]; then \
		echo "Error: current branch is '$$current'; expected '$(EXPECTED_BRANCH)'." >&2; \
		echo "Override intentionally with EXPECTED_BRANCH=$$current." >&2; \
		exit 2; \
	fi

status: repo-check
	@echo "Branch: $$($(GIT) branch --show-current)"
	@echo 'Allowed scope:'
	@printf '  %s\n' $(ALLOWED_PATHS)
	@echo 'Working tree:'
	@$(GIT) status --short --untracked-files=all -- $(ALLOWED_PATHS) || true
	@echo 'Staged:'
	@$(GIT) diff --cached --name-status -- $(ALLOWED_PATHS) || true

excluded: repo-check
	@echo 'Local files intentionally excluded from staging:'
	@find "$(REPO_ROOT)/$(WORKFLOW_BUILDER_PATH)" -mindepth 1 \
		\( -type d \( \
			-name .ucagent -o -name .workflow_builder -o -name __pycache__ \
			-o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \
			-o -name .cache -o -name workspace -o -name tmp \
			-o -name .claude -o -name .qwen -o -name .codex -o -name .gemini \
			-o -name .cursor -o -name .aider \
			-o -name .continue -o -name .windsurf -o -name .roo -o -name .kilocode \
			-o -name node_modules \
		\) -prune -print \) -o \
		\( -type f \( \
			-iname 'CLAUDE*.md' -o -iname 'AGENTS*.md' -o -iname 'GEMINI*.md' \
			-o -iname copilot-instructions.md -o -name .mcp.json \
			-o -name '.claude.*' -o -name '.qwen.*' -o -name '.codex.*' \
			-o -name '.gemini.*' -o -name '.cursor.*' -o -name '.aider*' \
			-o -name '*.pyc' -o -name '*.pyo' -o -name '*.log' \
			-o -name '*.tmp' -o -name '*.swp' -o -name .DS_Store \
		\) -print \) | sed "s#^$(REPO_ROOT)/##" | sort

preview: branch
	@echo 'Safe staging dry-run:'
	@$(GIT) add --dry-run -A -- $(STAGE_PATHS)

stage: branch
	@$(GIT) add -A -- $(STAGE_PATHS)
	@forbidden="$$($(GIT) diff --cached --name-only -- $(ALLOWED_PATHS) \
		| grep -Ei '$(FORBIDDEN_RE)' || true)"; \
	if [[ -n "$$forbidden" ]]; then \
		echo 'Removing forbidden paths from the staging area:'; \
		while IFS= read -r path; do \
			[[ -n "$$path" ]] || continue; \
			echo "  $$path"; \
			$(GIT) restore --staged -- "$$path"; \
		done <<< "$$forbidden"; \
	fi
	@$(MAKE) --no-print-directory -f "$(THIS_MAKEFILE)" verify

verify: branch
	@set -o pipefail; \
	staged="$$($(GIT) diff --cached --name-only)"; \
	if [[ -z "$$staged" ]]; then \
		echo 'Error: no staged changes in the allowed scope.' >&2; exit 2; \
	fi; \
	outside="$$(printf '%s\n' "$$staged" | awk \
		-v workflow='$(WORKFLOW_BUILDER_PATH)/' \
		-v docs='$(WORKFLOW_BUILDER_DOCS_PATH)/' \
		-v nav='$(DOCS_NAV_PATH)' \
		-v pandoc='$(DOCS_PANDOC_PATH)' \
		-v helper='$(COMMIT_MAKEFILE_PATH)' \
		'$$0 == nav || $$0 == pandoc || $$0 == helper || index($$0, workflow) == 1 || index($$0, docs) == 1 { next } { print }')"; \
	if [[ -n "$$outside" ]]; then \
		echo 'Error: staged paths outside the allowed scope:' >&2; \
		printf '  %s\n' $$outside >&2; exit 2; \
	fi; \
	forbidden="$$(printf '%s\n' "$$staged" | grep -Ei '$(FORBIDDEN_RE)' || true)"; \
	if [[ -n "$$forbidden" ]]; then \
		echo 'Error: forbidden cache/runtime/AI-assistant paths are staged:' >&2; \
		printf '  %s\n' $$forbidden >&2; exit 2; \
	fi
	@$(GIT) diff --cached --check
	@limit=$$(( $(MAX_FILE_MB) * 1024 * 1024 )); failed=0; \
	while IFS= read -r -d '' path; do \
		[[ -f "$(REPO_ROOT)/$$path" ]] || continue; \
		size=$$(wc -c < "$(REPO_ROOT)/$$path"); \
		if (( size > limit )); then \
			printf 'Error: staged file exceeds %s MiB: %s (%s bytes)\n' \
				'$(MAX_FILE_MB)' "$$path" "$$size" >&2; failed=1; \
		fi; \
	done < <($(GIT) diff --cached --name-only -z); \
	(( failed == 0 ))
	@echo 'Staged content passed scope, forbidden-path, whitespace, and size checks.'

review: verify
	@$(GIT) diff --cached --stat
	@$(GIT) diff --cached --color=always

commit: repo-check
	@test -n "$(strip $(MSG))" || { \
		echo 'Error: MSG is required. Example:' >&2; \
		echo '  make -f Commit.mk commit MSG="workflow_builder: improve documentation"' >&2; \
		exit 2; \
	}
	@$(MAKE) --no-print-directory -f "$(THIS_MAKEFILE)" stage
	@$(GIT) commit -m "$(MSG)"

unstage: repo-check
	@paths="$$($(GIT) diff --cached --name-only -- $(ALLOWED_PATHS))"; \
	if [[ -n "$$paths" ]]; then \
		while IFS= read -r path; do \
			[[ -n "$$path" ]] || continue; \
			$(GIT) restore --staged -- "$$path"; \
		done <<< "$$paths"; \
	fi
	@echo 'Allowed scope unstaged; working-tree files were not changed.'

# This intentionally removes only reproducible caches. Runtime history and AI
# client state remain untouched and are merely excluded from commits.
clean-cache: repo-check
	@find "$(REPO_ROOT)/$(WORKFLOW_BUILDER_PATH)" -type d \
		\( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache \
		-o -name .ruff_cache -o -name .cache \) -prune -exec rm -rf {} +
	@find "$(REPO_ROOT)/$(WORKFLOW_BUILDER_PATH)" -type f \
		\( -name '*.pyc' -o -name '*.pyo' -o -name '*.tmp' -o -name '*.swp' \) -delete
	@echo 'Reproducible caches removed; runtime history and AI client state were preserved.'
