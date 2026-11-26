"""Check the agent-first documentation entry and executable workflow examples."""

from pathlib import Path
import re
import shlex

from ucagent.cli import get_args

import pytest


PROJECT = Path(__file__).resolve().parents[1]


def test_readme_has_one_agent_request_instead_of_shell_setup() -> None:
    """Keep the public entry concise and link setup and targets to dedicated documents."""
    text = (PROJECT / "README.md").read_text(encoding="utf-8")
    requests = re.findall(r"```text\n(.*?)\n```", text, flags=re.DOTALL)
    assert len(requests) == 1
    request = requests[0]
    assert "plugins/ACT4/docs/agent-run.md" in request
    assert "codex" in request
    assert "privileged-suite-generation" in request and "Sstc" in request
    assert len(re.findall(r"【[^】]+】", request)) == 5
    assert "```bash" not in text
    assert "ACT4-SUITES:START" not in text
    assert "(docs/test-suites.md)" in text
    assert "(docs/agent-run.md)" in text


@pytest.mark.parametrize("document", [
    "docs/agent-run.md", "docs/generation.md", "docs/review.md", "docs/xiangshan.md",
    "src/ucagent_act4/Guide_Doc/ACT4_Extension_Review_Guide.md",
    "src/ucagent_act4/Guide_Doc/ACT4_XiangShan_Handoff_Guide.md",
    "src/ucagent_act4/Guide_Doc/ACT4_Privileged_Suite_Workflow_Guide.md",
])
def test_workflow_launch_examples_start_codex_and_exit_after_completion(document, monkeypatch) -> None:
    """Validate documented commands through the real CLI, including Codex's MCP dependency."""
    text = (PROJECT / document).read_text(encoding="utf-8")
    examples = re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL)
    commands = [line for example in examples for line in example.replace("\\\n", " ").splitlines()
                if "--plugin-workflow" in line]
    assert commands or "act4-run " in text or "run-configuration.md" in text or "ACT4_Run_Guide.md" in text
    for command in commands:
        assert "--backend codex" in command
        assert "--loop" in command
        assert "--exit-on-completion" in command
        assert "--mcp-server-no-file-tools" in command
        arguments = shlex.split(command)
        monkeypatch.setattr("sys.argv", arguments[arguments.index("ucagent"):])
        parsed = get_args()
        assert parsed.backend == "codex"
        assert parsed.mcp_server_no_file_tools and parsed.loop and parsed.exit_on_completion


def test_documentation_links_resolve_after_moving_setup_and_targets() -> None:
    """Keep local entry links valid and remove references to the replaced README sections."""
    documents = [PROJECT / "README.md", *(PROJECT / "docs").glob("*.md")]
    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "README.md#" not in text
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in link or link.startswith("#"):
                continue
            assert (document.parent / link.split("#", 1)[0]).exists(), (document, link)
