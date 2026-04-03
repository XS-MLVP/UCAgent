# Picker Quick Reference

This skill assumes the local Picker installation lives at:

- executable: `/nfs/home/share/unitychip/bin/picker`
- preferred PATH prefix: `/nfs/home/share/unitychip/bin`

## First diagnostics

```bash
PATH=/nfs/home/share/unitychip/bin:$PATH /nfs/home/share/unitychip/bin/picker --help
PATH=/nfs/home/share/unitychip/bin:$PATH /nfs/home/share/unitychip/bin/picker --check
```

For this workflow, `picker --check` only needs Python support to be healthy.

## Baseline export pattern

Use a target directory named after the DUT package you want to import:

```bash
PATH=/nfs/home/share/unitychip/bin:$PATH \
/nfs/home/share/unitychip/bin/picker export \
  --autobuild=true \
  ../UCAgent_Gencov/UCAgent/examples/Adder/Adder.v \
  --sname Adder \
  --tdir /tmp/pytoffee_skill_ws/exports/Adder \
  --lang python \
  -e -c \
  --sim verilator
```

## Import pattern after export

```bash
PYTHONPATH=/tmp/pytoffee_skill_ws/exports:$PYTHONPATH \
python3 -c "import Adder; print(Adder.DUTAdder)"
```

This is the layout expected by the generated API template:

```python
from Adder import DUTAdder
```

## Common options in this workflow

- `export` — generate a software-facing DUT package
- `--autobuild=true` — build the package during export
- `--sname <DUT>` — choose the top module / DUT name
- `--tdir <dir>` — export target directory; this must not already exist
- `--lang python` — build the Python-facing package
- `-e -c` — keep the local export pattern used by the current workflow
- `--sim verilator` — choose the simulator backend

## Failure patterns

### `sh: verible-verilog-syntax: not found`

- PATH does not include `/nfs/home/share/unitychip/bin`

### `Create: <dir> fail`

- `--tdir` already exists
- choose a fresh export directory

### export succeeds but `import {DUT}` fails

- you exported into the wrong directory name
- fix the export path to `<workspace>/exports/{DUT}` and put `<workspace>/exports` on `PYTHONPATH`
