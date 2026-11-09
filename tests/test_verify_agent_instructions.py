"""Generated agent instructions preserve canonical Markdown heading spacing."""

from ucagent import VerifyAgent
from ucagent.util.markdown import markdown_heading_spacing_errors

def test_generated_instruction_file_has_blank_lines_before_every_heading(tmp_path):
    dut_dir = tmp_path / "Adder"
    dut_dir.mkdir()
    (dut_dir / "README.md").write_text(
        "# DUT Overview\nDetails\n",
        encoding="utf-8",
    )
    agent = VerifyAgent.__new__(VerifyAgent)
    agent.workspace = str(tmp_path)
    agent.dut_name = "Adder"
    agent._default_system_prompt = "## Required Work\nRun verification."

    agent.generate_instruction_file("AGENT.md")

    content = (tmp_path / "AGENT.md").read_text(encoding="utf-8")
    assert markdown_heading_spacing_errors(content) == []
    assert content.startswith("\n# Goal Description\n")
