"""Normalize DUT RTL and documentation for a fresh Formal task."""
from ucagent.core.workspace.preparation import rtl_source


def prepare_formal(ctx):
    """Use original RTL inputs and exclude prior simulator and verification outputs."""
    root = rtl_source(ctx.source, ctx.dut_name)
    target = ctx.workspace / ctx.dut_name
    target.mkdir()
    ctx.progress("Preparing Formal RTL and documentation")
    for path in sorted(root.iterdir()):
        if path.name.startswith('.') or path.name in {"__pycache__", "unit_test", "uc_test_report", "formal_test", ctx.dut_name}:
            continue
        if path.is_dir() or path.suffix in {".v", ".sv", ".vh", ".svh", ".txt", ".md", ".tcl", ".sdc"}:
            ctx.copy(path, target / path.name)
    docs = ctx.source / f"{ctx.dut_name}_Doc"
    if docs.is_dir():
        ctx.copy(docs, target / "Doc")
