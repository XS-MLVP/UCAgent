
# RTL2Spec Documentation Generation

RTL2Spec is an on-demand UCAgent plugin located in `plugins/RTL2Spec/`. The current workflow targets the XiangShan module, combining Chisel/Scala source code with the corresponding RTL generated in the same commit and configuration, to deliver Chinese design and functional verification point documentation and quality reports.

The workflow consists of three stages:

1. **Generate Evidence**: Check the tool environment and source code, generate RTL, port lists, and an evidence list.
2. **Write Documentation**: Organize module behavior, interfaces, and verification plans according to templates; content that cannot be confirmed is retained as `OPEN-*`.
3. **Acceptance**: Preserve the Mermaid source and verify the consistency of the document structure, evidence, and references.

To begin, install UCAgent, then install the plugin from the repository root directory:

```bash
python -m pip install ./plugins/RTL2Spec
ucagent --validate-plugin rtl2spec
```

Complete input preparation, Sbuffer execution examples, output paths, and environment requirements are centrally maintained in the [RTL2Spec README](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/RTL2Spec/README.md). After document acceptance passes, human review of design intent is still required; it does not represent SVA compilation or formal proof success.

For extending the plugin, refer to [Plugin Development and Release](../03_develop/09_plugins.md).
