
# FAQ

## Models and Configuration

### How to switch models?

You can temporarily switch models using environment variables:

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

You can also modify fields such as `openai.model_name` in the project's `config.yaml`, or specify a different configuration file using `--config <path>`. For configuration priority, see [Workflow Configuration](../03_develop/03_workflow.md#3-configuration-loading-and-template-variables); for model environment variables, see [Parameter Description](./03_option.md).

### How to use `--no-embed-tools`?

The current CLI disables embedded/retrieval tools by default. Writing `--no-embed-tools` bare or passing `true` both disable the tools; to enable them, use:

```bash
--no-embed-tools false
```

Embedded tools are not a prerequisite for standard file tools or testing tools.

## Execution and Recovery

### UCAgent exited midway, how to recover?

First, confirm that the old UCAgent and any external Code Agent have exited, then restart with the same workspace, DUT, and configuration. Enter `status` to confirm the current phase, then enter `loop` or let the external Agent continue. Do not delete `.ucagent/` or output artifacts unless you explicitly intend to start over.

### What to do if a Check fails?

First, read the `artifact`, `location`, `observed`, `expected`, and `next_action` returned by the Checker. If necessary, use:

```text
tool_invoke StdCheck lines=-1
tool_invoke KillCheck
```

After fixing, re-run the tests, `Check`, and `Complete`. Test infrastructure failures should be fixed to Pass first; only reproducible DUT failures with correct assertions should be recorded as Bugs.

### Why is `config.yaml` not found at startup?

`config.yaml` is a project configuration file, not a file necessarily provided by pip installation. You can:

- Create your own `config.yaml` in the workspace and pass `--config config.yaml`;
- Use the configuration and Makefile from the source repository;
- Omit `--config` to use the layered default configuration.

### Why is `--no-write` not taking effect?

The target must be located within the workspace. Regular files or directories must already exist; wildcard paths can match targets that have not yet been created. This option restricts UCAgent tool writes but does not prevent you from manually modifying files in an external shell.

## Tools and Terminology

### How to choose text file tools?

The current text file tools are:

- `EditTextFile`: Create, overwrite, or append to a complete text file;
- `ReplaceStringInFile`: Replace a unique segment of text in an existing file;
- `DeleteTextLines`: Delete multiple complete line blocks at once.

First use `ReadTextFile` to get the current content; pass `expected_sha256` when concurrent protection is required.

### How to distinguish between CK, TC, and Bug?

CK stands for functional check point, and TC stands for test case. Dynamic Bug entries should be associated with accurate FG/FC/CK and the failing TC; test infrastructure failures should not be recorded as DUT Bugs.

### How to troubleshoot MCP connection failures?

Confirm:

1. UCAgent is using `--mcp-server` or `--mcp-server-no-file-tools`;
2. The client address is `http://<host>:<port>/mcp`;
3. The client port matches `--mcp-server-port`;
4. For remote scenarios, `--mcp-server-host`, firewall, and permissions allow the connection.

The command-line backend must also have MCP parameters enabled; otherwise, the CLI will refuse to start.
