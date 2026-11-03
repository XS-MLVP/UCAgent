
# Normal Mode

Normal mode completes a verification task with a single UCAgent process. The default backend is `langchain`, and UCAgent connects directly to the model; manual operations are performed in the PDB/TUI console of the current terminal, without requiring an external Code Agent or MCP.

This chapter uses a 64-bit adder example where the `sum` bit width is intentionally truncated. The example is used to illustrate the workflow; actual projects should replace it with their own RTL and verification requirements.

## 2.1 Prepare the DUT

Create the RTL input directory in the project directory (the `output/` directory under it will later be used as the UCAgent workspace):

```bash
mkdir -p Adder
```

`Adder/Adder.v`:

```verilog
module Adder #(
    parameter WIDTH = 64
) (
    input  [WIDTH-1:0] a,
    input  [WIDTH-1:0] b,
    input              cin,
    output [WIDTH-2:0] sum,
    output             cout
);
    assign {cout, sum} = a + b + cin;
endmodule
```

Also prepare `Adder/README.md` to clearly define the expected behavior, for example:

```markdown

# Adder Verification Requirements

Verify a 64-bit unsigned combinational adder with no clock and no reset.

- Inputs: `a` and `b` are each 64 bits; `cin` is a 1-bit carry input.
- Expected Outputs: `sum` is the lower 64 bits of the result; `cout` is the 65th bit (carry out).
- Operation Rule: The full result equals the unsigned `a + b + cin`; no result bits may be lost.
- Verification Scope: Zero values, maximum values, carry cases, boundary combinations, and random inputs.
```

The RTL here intentionally provides one fewer bit for `sum` to demonstrate detecting inconsistencies with the specification. In actual projects, interfaces, timing, and constraints should be clearly documented; the README is a workflow input, and the Agent should not be allowed to guess the specification on its own.

## 2.2 Export the Python DUT Package

picker exports the RTL as a DUT package that can be driven by Python. The following command writes the package to `output/Adder/` and sets the waveform output path for simulation:

```bash
picker export Adder/Adder.v --rw 1 --sname Adder --tdir output/ -c -w output/Adder/Adder.fst
cp Adder/README.md output/Adder/README.md
cp Adder/Adder.v output/Adder/Adder.v
```

The minimal structure after preparation is complete:

```text
<project>/
├── Adder/
│   ├── Adder.v
│   └── README.md
└── output/            # workspace for this example
    └── Adder/          # Python package exported by picker
        └── xspcomm/
```

First, verify that the generated Python package can be loaded and driven:

```bash
PYTHONPATH=output python3 - <<'PYTHON'
from Adder import DUTAdder

dut = DUTAdder()
dut.a.value = 0
dut.b.value = 0
dut.cin.value = 0
dut.Step(1)
assert dut.sum.value == 0 and dut.cout.value == 0
dut.Finish()
print("DUT import and zero-input simulation passed")
PYTHON
```

If this step fails, fix picker or the simulation environment first before starting UCAgent. The Makefile in the source repository provides another path, which automatically copies `examples/<DUT>` and runs picker; see the next section.

## 2.3 Configure the Model

The LangChain backend uses an OpenAI-compatible interface. The minimal configuration is:

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

You can also write `openai.model_name`, `openai.openai_api_key`, and `openai.openai_api_base` in `config.yaml`. See [Workflow Configuration](../03_develop/03_workflow.md#3-configuration-loading-and-template-variables) for configuration loading order and override rules.

The built-in configuration treats `--no-embed-tools` as enabled by default, meaning embedded/retrieval tools are disabled. If you need to use these tools, pass it explicitly:

```bash
--no-embed-tools false
```

This only affects embedded tools, not regular file and test tools.

## 2.4 Start Verification

Continue using the manually prepared `output/Adder/` from this chapter, and start it in the project directory:

```bash
ucagent output/ Adder -s -hm --tui -l
```

You can also use the `examples/Adder/` included in the repository from the UCAgent source root directory, skipping the manual preparation steps in this chapter:

```bash
make test_Adder
```

The Makefile uses a separate workspace `output/workspace_Adder/`, and the core command executed is:

```bash
python3 ucagent.py output/workspace_Adder/ Adder \
  --config config.yaml -s -hm --tui -l
```

`-l/--loop` makes the task enter the model loop immediately; if omitted, you must type `loop` in the console after startup to continue. Normal mode does not start MCP, so external Code Agents like opencode will not run automatically.

## 2.5 Intervention During Execution

Type `status` at the bottom of the TUI to view the phase status, and type `current_tips` to view guidance for the current phase. To pause, press `Ctrl+C`; after fixing files or the environment, use `tool_invoke Check` to verify, then type `loop` to continue. See [Human-in-the-Loop Verification](../02_usage/02_assit.md) and [TUI](../02_usage/04_tui.md) for complete commands and the human review process.

## 2.6 Result Locations

The default output directory is `unity_test/` under the workspace, and test reports are usually located in `uc_test_report/`. The workspace for the Makefile example is `output/workspace_Adder/`, so artifacts are located under that directory; artifacts for the direct CLI example are located in `output/unity_test/`. See [Result Analysis and Workflow Summary](06_summary.md) for file purposes.
