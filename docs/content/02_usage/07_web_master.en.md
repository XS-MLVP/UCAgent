
# Web Master User Guide

This document provides the complete operational workflow for UCAgent Web Master:

1. Access the Master dashboard to view Agent status
2. Create and compile tasks on the Launch page
3. Manage task lifecycle on the Task page
4. Perform batch stage operations and review results on the Agent page

---

## 1. Feature Overview

Web Master is not just a status display; it is a complete task management entry point. Core capabilities include:

1. Dashboard: Agent list, filtering, sorting, pagination, and offline policies
2. Launch: Workspace creation, file import/upload, module parsing, compilation, and launch parameter preview
3. Task: Hosted task list, status filtering, log viewing, stop/delete
4. Agent: Stage quick actions (HM/Skip/LFail/LPass), stage file viewing, and Diff comparison
5. Web Terminal: Online terminal access (can run in parallel with local terminals)

---

## 2. Quick Start

### 2.1 Starting Master

Master retains a local PDB console for executing Master API, task, terminal, status, and file management commands, but it does not initialize, probe, or invoke API/command-line model backends. When executing model work commands such as `loop`, `chat`, or `next_round`, `BlankBackend` directly returns "not supported" and does not invoke the model.

```bash

# Source repository: temporary workspace

make as_master

# Recommended: persistent workspace

make as_master_persist

# Installed command

ucagent --as-master-persist --as-master
```

Default access address:

```text
http://localhost:8800
```

If password protection is required:

```bash
ucagent --as-master-persist --as-master --as-master-password "your_password"
```

Starting Master itself does not require a model address, API Key, or model name. If you need to launch child Agents from the Launch page, you can configure model variables in the Master process environment; these are only used to construct the launch environment for child Agents.

The `--backend` flag in Master mode is used to set the default backend when launching child Agents from the Launch page; the current Master process always uses a model-less backend.

### 2.2 Connecting Agent to Master

```bash
ucagent ./output Adder --master 127.0.0.1:8800 your_key
```

Example:

```bash
ucagent ./output Adder --master 127.0.0.1:8800
```

---

## 3. Dashboard (Overview Page)

### 3.1 Common Operations

1. Search Agents (ID/Host/Mission)
2. Filter by status (online/offline)
3. Sort by fields (last_seen/progress, etc.)
4. Paginate through large-scale Agent lists
5. Batch delete offline Agents

### 3.2 Offline Cleanup Policy

You can enable Auto-delete offline and set the check interval and threshold time to reduce interference from zombie instances on the panel.

Recommendations:

1. Development environment: Shorter threshold (e.g., 5-10 minutes)
2. Shared environment: Longer threshold (e.g., 30-60 minutes)

---

## 4. Launch (Task Creation Page)

### 4.1 Standard Workflow

1. Create a Launch Workspace
2. Upload or import RTL/Spec/Requirement/Config files
3. Mark the main RTL and parse modules
4. Select DUT name and module, then execute compilation
5. Check the command preview and launch the hosted task

### 4.2 Best Practices

1. Recompile after every adjustment to the main module
2. Retain version tags for Requirement and Config to facilitate traceability
3. Review the Command Preview before launching to confirm backend/master/export-cmd-api parameters

### 4.3 Parallel Task Limit and Waiting Queue

`master_api.max_task_count` controls the maximum number of tasks Master can execute simultaneously, defaulting to 100:

1. Tasks launched after reaching the limit enter the waiting state and do not occupy execution quota
2. Once a task finishes and releases quota, waiting tasks are automatically launched in launch order
3. Waiting tasks are only listed in the Launch Queue panel on the Task page (including task ID, DUT, creation and enqueue time, etc.); the main task list does not display waiting tasks
4. The Launch Queue panel supports drag-and-drop or ▲▼ buttons to adjust the launch order of waiting tasks; resubmitted tasks are placed at the end of the queue
5. The Waiting statistic on the Master page is displayed at the same level as TOTAL/ONLINE/OFFLINE to show the current number of waiting tasks
6. The Task page summary bar persistently displays the current maximum concurrency (`master_api.max_task_count`)
7. Waiting tasks can be cancelled in the Launch Queue panel; cancellation deletes the task record and its workspace directory

---

## 5. Task (Hosted Task Page)

### 5.1 Page Capabilities

1. Filter by status, keyword, and DUT (waiting tasks are only displayed in the Launch Queue panel, see 4.3)
2. Paginate through tasks
3. View task details (command, registration status, PID)
4. View stdout/stderr logs
5. Stop tasks and delete records
6. Adjust the launch order of waiting tasks and cancel waiting tasks in the Launch Queue panel (see 4.3)

### 5.2 Typical Troubleshooting Path

1. Task stuck in starting: First check the command and environment variable expansion results
2. Task failed: Prioritize checking stderr, then check workspace and DUT parameters
3. Agent not registered: Check --master address, key, and network connectivity
4. Task always waiting: Parallel tasks have reached the `master_api.max_task_count` limit; the queue position is visible in the details page, wait for automatic launch or cancel the task

---

## 6. Advanced Operations on Agent Page

### 6.1 Stage Quick Controls

The page supports single-stage quick toggles:

1. HM: Human review toggle
2. Skip: Skip toggle
3. LF: LLM Fail Suggestion toggle
4. LP: LLM Pass Suggestion toggle

### 6.2 Stage Batch Controls

You can select multiple stages and batch set:

1. HM On/Off
2. Skip/Unskip
3. LFail On/Off
4. LPass On/Off

### 6.3 Stage Artifact Review

For stage output files, you can:

1. View content
2. View Diff (comparison between current result and changes)
3. Quickly locate artifacts corresponding to failed stages

---

## 7. Web Terminal and Access Modes

### 7.1 Two Common Modes

1. web-console: Browser console mode (independent Web entry)
2. web-terminal: Web terminal mode (can run in parallel with local terminals)

### 7.2 Multi-Session Recommendations

When enabling multiple terminal sessions, it is recommended to distinguish tasks via different URLs/tabs to avoid accidental operations.

---

## 8. Proxy and Network Notes

Master supports unified proxy forwarding to task/agent cmd, terminal, and web-console access paths.

When connection issues occur, troubleshoot in the following order:

1. Master page visible but sub-pages fail: Check proxy paths and authentication
2. Page opens but WS is unstable: Check if the reverse proxy/gateway allows websocket
3. Local connects but remote does not: Check binding address (127.0.0.1 vs 0.0.0.0)

---

## 9. Security and Permission Recommendations

1. Always enable password protection for public or shared networks
2. Use gateway authentication and TLS when exposing externally
3. Regularly clean up offline Agents and invalid task records

---

## 10. FAQ

### Q1: Why does Launch compilation succeed but task launch fail?

Prioritize checking:

1. Whether the backend is available
2. Whether launch environment variables are complete
3. Whether the master address and key are correct

### Q2: Why does Task show running, but the Agent page cannot be opened?

This is usually due to registration delay or proxy chain issues; first check the registration status and logs in Task details.

### Q3: When to use TUI and when to use Web?

1. TUI: Local quick debugging, fine-grained command operations
2. Web: Centralized management, multi-task operations, remote collaboration
