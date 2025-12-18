# Repository Guidelines

## Project Structure & Module Organization
- `ucagent/`: Core package; CLI entrypoint (`cli.py`), verification stages (`stage/`), tools (`tools/`), checkers (`checkers/`), interaction/TUI code, language packs, and configuration defaults.
- `ucagent.py`: Thin wrapper to launch the agent from a workspace.
- `tests/`: Pytest suite covering CLI utilities, stages, tools, and UI helpers.
- `examples/`: Sample DUTs with `unity_test/` fixtures and test cases; useful for local trials.
- `docs/`: MkDocs + Pandoc sources and build helpers; generated artifacts land in `docs/site` or `ucagent-doc.pdf`.

## Setup, Build & Run
- Python 3.11+ required. Install runtime deps: `make init` or `pip3 install -r requirements.txt`.
- Prepare a DUT workspace (e.g., Adder): `make init_Adder` (copies RTL/files into `output/Adder_RTL` and exports to `output/Adder/`).
- Run the agent with TUI + history: `make test_Adder ARGS='-l DEBUG' CFG=config.yaml` or directly `python3 ucagent.py output/ Adder --config config.yaml -s -hm --tui`.
- Start MCP server mode: `make mcp_Adder` (or `make mcp_all_tools_Adder` to include file tools).
- Clean build/test artifacts: `make clean` (use `clean_test` to wipe only `output/unity_test`).

## Development & Testing
- Unit tests: `pytest -s tests` for the full suite; target files with `pytest tests/test_fileops.py -k path`.
- Example DUT tests: run under `output/<dut>/unity_test/` via pytest args passed to the agent (`ARGS='-- -k smoke'` when invoking `make test_<dut>`).
- Keep fixtures explicit: `@pytest.fixture` on `dut`/`env`, tests named `test_*` and accept the `env` fixture first when applicable.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation; prefer type hints and module-level docstrings (see `ucagent/cli.py`).
- Use descriptive, verb-first function names; keep modules cohesive (tools in `ucagent/tools/`, stages in `ucagent/stage/`).
- Config is YAML (`config.yaml`, `ucagent/setting.yaml`); keep keys lowercase with underscores.
- Tests live under `tests/` and example suites under `examples/*/unity_test/tests/`; name files `test_<feature>.py`.

## Documentation
- Preview docs: `make docs-serve` (http://127.0.0.1:8030). Build static site: `make docs-build`. Remove artifacts: `make docs-clean`.
- Generate PDF manual (Pandoc + XeLaTeX): `make pdf` and clean with `make pdf-clean`.

## Commit & Pull Request Guidelines
- Commit messages follow a light Conventional Commits style seen in history: `fix(makefile): refine clean`, `add Inc Test example`. Use `type(scope): summary` where scope is optional.
- PRs should state intent, test coverage (`pytest`/`make test_<dut>` commands run), and any config impacts. Link issues when relevant and include screenshots or logs for TUI/output changes.
