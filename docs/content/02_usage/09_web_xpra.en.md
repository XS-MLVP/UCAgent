
# Xpra GUI Applications and Interactive Console

The CMD WebUI can display server-side graphical applications in the browser via Xpra, or run interactive commands through a graphical terminal. The **Xpra** button on the Agent Dashboard opens the session management page; clicking **Create session** opens the creation dialog; the **Open** link for each session directly opens the application display page. The display page uses the UCAgent interface, reusing the protocol and rendering libraries of the official HTML5 client, and no longer displays the official connection form.

Sessions belong to the CMD service that created them. They do not discover, take over, or delete Xpra sessions started by other users or services on the same machine. Web Terminal, Web Console, and Xpra use independent connections and can run simultaneously.

## Installation and Startup Requirements

Install the Xpra server, X11 service support, a virtual display program (such as Xvfb), and the official `xpra-html5` client in the environment where the CMD service runs. Console mode also requires a graphical terminal, which defaults to `xterm`. Real integration verification uses Xpra 6.5.5 as the baseline.

The CMD service and target applications can be deployed on Linux hosts or Docker containers that have the above dependencies. Users access the session management page and application display page via a browser. Direct connection and Master proxy access have been verified on macOS using Chrome and WebKit.

The CMD service can still start if Xpra is missing, and other APIs remain available. The management page will display prompts indicating missing programs or resources. The `status` endpoint checks executables, versions, and explicitly configured resource paths; when actually creating a session, it further checks whether the server and HTML5 service can start.

Follow the CMD service's startup and authentication settings, for example, execute in PDB:

```text
cmd_api_start --passwd your-password
```

Access `http://127.0.0.1:8765/api/xpra/` directly, using the same Basic authentication as other CMD APIs. If the CMD service has no password configured, Xpra also allows passwordless access. HTML5 pages, resources, and WebSockets are also subject to this policy; passwords are not written into the connection URL. After entering the management page and completing CMD or Master login, clicking **Open** will automatically check access permissions and connect based on the session ID in the URL, without requiring re-entry of the Xpra host, port, username, or password. The session ID itself does not grant access permissions; unauthenticated new browsers must still complete the login for the current entry point first.

Some browsers do not include the page's Basic authentication header in the WebSocket handshake. Before each connection, the display page obtains a connection Cookie with a 5-minute validity period via an authenticated HTTP request; the Cookie uses HttpOnly, SameSite=Strict, and also uses Secure under HTTPS, and is only applicable to the WebSocket of the current session and current proxy path. It cannot be used to call management interfaces, nor can it be used by other sessions; once the connection is established, it will not be disconnected due to Cookie expiration, and it is automatically re-issued upon reconnection. Command-line WebSocket clients can still directly use Basic authentication.

## Configuration

Place the following settings in the UCAgent configuration file; fields are read from the currently effective configuration, and the CMD service must be restarted after modifications:

```yaml
cmd_api:
  xpra:
    executable: xpra
    max_sessions: 5
    terminal_command: [xterm, -e]
    html_dir: null
    startup_timeout: 20
    shutdown_timeout: 5
    presets:
      - label: Terminal
        name: Terminal
        mode: console
        command: bash -l
        cwd: .
        env: {}
        idle_timeout: -1
      - label: Browser
        name: Browser
        mode: gui
        command: chromium --no-first-run --no-default-browser-check about:blank
        cwd: .
        env: {}
        idle_timeout: -1
      - label: Codex
        name: Codex
        mode: console
        command: codex
        cwd: .
        env: {}
        idle_timeout: -1
      - label: OpenCode
        name: OpenCode
        mode: console
        command: opencode
        cwd: .
        env: {}
        idle_timeout: -1
      - label: Qwen Code
        name: Qwen Code
        mode: console
        command: qwen
        cwd: .
        env: {}
        idle_timeout: -1
```

| Field | Purpose |
| --- | --- |
| `executable` | Xpra program name or executable file path |
| `max_sessions` | Number of simultaneously active sessions, default 5; must be a positive integer |
| `terminal_command` | List of startup arguments for the Console graphical terminal, followed by the appended application command and its arguments |
| `html_dir` | Official HTML5 resource directory, must contain `index.html`; `null` uses Xpra's built-in resources |
| `startup_timeout` | Seconds to wait for the HTML5 service to be ready, must be a positive number |
| `shutdown_timeout` | Seconds to wait for the associated Xpra to stop normally, forcibly reclaims after timeout |
| `presets` | List of shortcut buttons for the creation form; `[]` hides all buttons. A custom list completely replaces the default list |

Xpra uses a private temporary directory and Unix socket, and does not open an additional Xpra TCP port. Sessions isolate Xpra's system/user configuration directories to prevent listening settings or additional startup commands within them from bypassing CMD management; adjust this feature via the above UCAgent configuration.

## Creation Shortcut Buttons and Code Agent

The creation form provides **Terminal**, **Browser**, **Codex**, **OpenCode**, and **Qwen Code** shortcut buttons by default. Clicking **Create session** opens the creation dialog, which provides these shortcut buttons. Clicking a button completely fills in the name, mode, command, working directory, environment variables, and idle timeout; only after confirming or modifying the parameters and clicking **Create session** will the program start. The buttons themselves do not start sessions, nor do they occupy quota.

**Terminal** uses Console mode to start `bash -l`, displaying an interactive shell through the configured graphical terminal; the command can be changed to installed shells such as `zsh -l`. **Browser** uses GUI mode to start `chromium --no-first-run --no-default-browser-check about:blank`; the command can be changed to the actual browser path or programs like Firefox. The browser runs in the environment where the CMD service is located, and the corresponding programs need to be installed there; the accessed network and files also come from that service environment.

Each `presets` entry includes required `label` (button text) and `command`; other fields are consistent with the creation interface: `name` defaults to an empty string, `mode` defaults to `gui`, `cwd` defaults to `.`, `env` defaults to `{}`, and `idle_timeout` defaults to `-1`. Code Agent presets should explicitly use `mode: console` to run the interactive interface through the configured graphical terminal. The command can be modified to the absolute path of the executable file, or parameters supported by that CLI can be appended; the working directory must still be located within the workspace.

`codex`, `opencode`, and `qwen` must be installed in the **environment where the CMD service actually runs** and be findable via its PATH; if CMD runs in a container, CLI installations on the host machine will not automatically appear in the container. Presets use interactive startup commands; the CLI's own first-time login, model configuration, and authorization are still completed by that CLI. If the command is missing, the creation interface and page will prompt to install the program or correct the path.

Preset parameters are sent to the browser via the authenticated API for user viewing and editing. Do not put API keys, tokens, or passwords in preset commands or `env`; set the required credentials in the CMD runtime environment, and let child processes inherit them. Shortcut buttons do not modify the Code Agent's login configuration or approval options.

The preset list can still be read even if Xpra or the target CLI is missing. If the format is invalid, the page displays a configuration error, and the manual creation form remains available. Restart the CMD service after modifying the configuration.

## API

All interfaces uniformly use the `/api/xpra/` prefix.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/xpra/` | Session management page |
| GET | `/api/xpra/status` | Program availability, version, Console terminal availability, and diagnostics |
| GET | `/api/xpra/presets` | Returns `{"presets": [...]}`, for the creation page to fill parameters; follows CMD/Master authentication |
| GET | `/api/xpra/sessions` | List of owned sessions, active count, maximum count |
| POST | `/api/xpra/sessions` | Create session; returns 201 after the HTML5 service is ready |
| GET | `/api/xpra/sessions/{id}` | Single session details, recent errors, and length-limited logs |
| DELETE | `/api/xpra/sessions/{id}` | Stop and delete the owned session |
| POST | `/api/xpra/sessions/{id}/connect` | Check the session and issue or refresh the connection Cookie for the current browser, returns 204 on success; still requires CMD/Master HTTP authentication |
| GET | `/api/xpra/sessions/{id}/view` | HTML5 display page with automatic connection |
| GET / HEAD | `/api/xpra/sessions/{id}/client/{path}` | UCAgent application display interface and official protocol, rendering resources |
| WebSocket | `/api/xpra/sessions/{id}/client/` | Screen, keyboard/mouse, and client protocol interaction |

Create a GUI session:

```bash
curl -u :your-password \
  -H 'Content-Type: application/json' \
  -d '{"name":"Clock","mode":"gui","command":"xclock","cwd":".","env":{}}' \
  http://127.0.0.1:8765/api/xpra/sessions
```

Creating a Console session uses the same interface and fields, for example:

```json
{
  "name": "Interactive shell",
  "mode": "console",
  "command": "bash -l",
  "cwd": ".",
  "env": {"TERM": "xterm-256color"},
  "idle_timeout": 300
}
```

`command` is required; `mode` defaults to `gui`, `name` defaults to the startup program name, `cwd` defaults to the workspace root directory, and `env` defaults to an empty object. The working directory must exist and be located within the workspace; symbolic links cannot point to external directories.

Commands are split into arguments by quotes and do not automatically interpret shell expressions. When pipes, redirections, or shell initialization are needed, explicitly submit `bash -lc 'your command'`. Console mode appends the split arguments after `terminal_command`; GUI mode directly starts the application.

Sessions include `id`, `name`, `mode`, `command`, `cwd`, `idle_timeout`, `status`, `created_at`, `viewer_path`, and `last_error`; details also include `log_tail` with up to 200 lines of output. `viewer_path` is resolved relative to the current `/api/xpra/` base address. `created_at` is a Unix timestamp. Environment variable values are not returned as session fields; known credentials and submitted environment variable values are masked in captured logs.

## Display Page Operations

Clicking **Open** launches the application directly. The Console defaults to filling the available display area, while the GUI retains the application's own window size and adjustment capabilities. The top bar displays the actual connection status and provides **Reconnect**, **Full screen**, **Sessions**, **Exit**, and a window switch list; minimized applications can be restored via the window list.

In the Console, drag the mouse to select text, then right-click to choose **Copy selection** to copy to the local clipboard; right-click to choose **Paste** to paste local clipboard text into the terminal. Support for `⌘C` / `⌘V` and `Ctrl+Shift+C` / `Ctrl+Shift+V` is also available; ordinary `Ctrl+C` remains for terminal interruption. Opening a menu does not change the current selection, and the copy button is unavailable when no text is selected.

When the browser requires clipboard permissions, you must allow this visit. If standard HTTP, browser restrictions, or permission denial occur, a manual copy/paste window will open. You can also directly select **Paste text…**, perform the browser's paste operation in the local text box, and then click **Paste into terminal**. Content in the text box is not sent to the application before submission. Pasted text is sent as-is; newlines in the text may trigger terminal execution.

In the Console, hold a modifier key (Shift, Control, Command, or Alt) and right-click; the right-click is still handed to the remote application for its own menu or mouse functions. Right-clicks in GUI mode are always handed to the remote application; local browser menus do not pop up in the application area. Top navigation and buttons retain the browser's right-click behavior.

Clicking **Exit** and confirming will stop the application, delete the current session, and return to the session management page of the current entry; the current client will disconnect. During exit, automatic reconnection is paused; if it fails, the reason is displayed and retry is allowed. Closing the browser tab retains the application based on the idle timeout setting for that session.

Refreshing the page re-verifies and automatically connects. In case of temporary disconnection, automatic retry occurs up to 5 times, displaying the retry progress. If the session is deleted, exited, or access is denied, the specific reason and operation prompt are displayed without redirecting to the official connection page. Clicking **Reconnect** manually initiates a new connection. The initial connection does not proactively read the local clipboard or request audio permissions; clipboard interactions are triggered by user copy/paste operations.

Each session allows only one client control simultaneously. Newly opened display pages automatically preempt the original connection; the original page displays the **Session opened in another client** prompt and **Take back** button, stopping automatic reconnection. Clicking **Take back** reclaims the current page, and the other page receives the same prompt. Direct connection, Master task proxy, and agent proxy all adhere to this rule.

## Lifecycle and Error Handling

Status includes `starting`, `running`, `stopping`, `exited`, and `failed`. Sessions in starting, running, or stopping states occupy active quotas; exited or failed sessions do not occupy quotas but can still be viewed for logs or deleted.

An `idle_timeout` can be set during creation, in integer seconds: `-1` (default) means no timeout, a positive integer means the application exits automatically if no connected client has been present for that many seconds; `0`, other negative numbers, non-integers, or values exceeding `4294967` are invalid. Timing starts when the session service is ready and no client is connected; it is cancelled upon client connection and restarted after the last client disconnects. The session does not timeout even without keyboard/mouse input while a client maintains the connection; polling the management page, viewing details, and loading resources do not count as client connections. New clients during preemption continue the session.

After idle timeout exit, an `exited` record is retained in the list for viewing logs and deletion; active quotas and process resources are released. With `-1`, closing the browser or losing network connection retains the application; with a finite timeout, it can be reopened before expiration. Upon application exit, the session ends; deleting the session, stopping the CMD service, or normally exiting UCAgent cleans up associated Xpra, child processes, and temporary resources. Old sessions are not restored after service restart.

Interface failures return structured diagnostics via `detail`:

```json
{
  "detail": {
    "error_code": "XPRA_SESSION_LIMIT",
    "message": "The maximum number of active Xpra sessions has been reached.",
    "next_action": "Delete an unused session or increase cmd_api.xpra.max_sessions."
  }
}
```

| Status Code | Typical Cause | Action |
| --- | --- | --- |
| 401 | Missing or incorrect CMD / Master credentials | Use authentication info from the current entry |
| 404 | Session does not exist or has been deleted | Refresh the list and open an existing session |
| 409 | Capacity limit reached or creation cancelled by a stop operation | Delete idle sessions, or retry creation |
| 422 | Invalid command, working directory, environment variable, or request field | Correct input based on diagnostics |
| 502 | Unable to connect to upstream Xpra | Check session status and logs, then reconnect |
| 503 | Missing program, terminal, HTML5 resources, or server capabilities; session not running | Install/configure running conditions based on diagnostics, or create a new session |
| 504 | Startup did not complete within the time limit | Check logs, fix the display environment, and adjust startup wait time if necessary |

Creation failure returns a queryable `session_id` and logs; if submission parameters are invalid or the program does not exist, a session ID may not be allocated yet. The management page and display page directly display the error reason and next steps.

## Master Proxy and Existing Terminals

When accessing via an existing Master CMD proxy, prepend `/task/{task_id}/cmd` or `/agent/{agent_id}/cmd` to the above addresses, for example:

```text
/task/{task_id}/cmd/api/xpra/
/agent/{agent_id}/cmd/api/xpra/sessions/{id}/view
```

The management page, HTML5 resources, and WebSocket use the same proxy prefix. The browser uses Master authentication, providing corresponding credentials for the upstream CMD connection to Master. HTTPS pages automatically use WSS; when deployed behind an external reverse proxy, WebSocket Upgrade should continue to be allowed.

Agents update CMD proxy credentials to the connected Master via actual registration and heartbeat; Master uses these in memory for HTTP/WebSocket forwarding and does not return or save this password in the Agent list, details, or persisted Agent snapshots. Master credentials are restored by new heartbeats after Master restart.

Existing terminals maintain an independent `/ws` service; Master maintains `/terminal/ws` and `/web-console/ws`. Xpra uses `/api/xpra/sessions/{id}/client/` under CMD; deleting, refreshing, or reconnecting Xpra does not take over the terminal connection nor terminate the terminal process.

## Full Runtime Integration Test

In a Linux environment with the project's full dependencies, picker, Verilator, Xpra server, official HTML5 resources, Xvfb, xterm, and xclock installed, run:

```bash
UCAGENT_RUN_XPRA_INTEGRATION=1 python -m pytest -q tests/test_api_xpra_full_runtime.py
```

The test first exports and compiles a real DUT package from Adder RTL using picker and Verilator, then loads the default verification workflow via the formal CLI, verifying coexistence of Web Terminal, Web Console modes, and CMD API/Xpra. It checks real PDB command execution, terminal input/output, Master authentication proxy after actual heartbeat registration, GUI/Console session creation/deletion, and process cleanup after normal UCAgent exit. Web Terminal and Web Console for the same Agent follow the mutual exclusion limits of the CLI; tests can be run separately across multiple Agents. The test uses the project's built-in `blank` backend, does not initiate model requests, and does not replace Agent, PDB, or workflow objects. This test is skipped unless explicitly enabled; standard unit tests do not require local Xpra server installation.
