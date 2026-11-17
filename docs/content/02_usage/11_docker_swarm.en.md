
# Docker Swarm Deployment

This guide prepares a 2- or 3-node Docker Swarm cluster and starts the UCAgent
Master Web service with `make/master.mk`. Master runs as a Swarm service, and
verification tasks launched from the Master Web Launch page run as Swarm job
services.

The examples use Linux hosts and Docker Engine. Docker Desktop, Colima, and a
remote Docker context can use the same Make targets, but Docker socket mounts,
persistent paths, and the browser address must match the selected context.

## 1. Node plan

The example uses three hosts. With two hosts, omit the `swarm-worker-2` steps.

| Node | Example address | Role | Purpose |
| --- | --- | --- | --- |
| `swarm-manager-1` | `192.168.10.11` | manager | Run `make swarm_master` and host Master Web |
| `swarm-worker-1` | `192.168.10.12` | worker | Run verification jobs launched by Master Web |
| `swarm-worker-2` | `192.168.10.13` | worker | Optional second job node |

All nodes must reach one another by hostname or IP and use compatible Docker
Engine versions. The task image must be pullable by every node where a task may
run. The default image is `ghcr.nju.edu.cn/xs-mlvp/ucagent:latest`. The Make
targets do not automatically forward private registry credentials. For a private
image, log in and pull it on every eligible node first, or set `SWARM_IMAGE` to an
image address available to all nodes. The initial image is large; consider running
`docker pull <SWARM_IMAGE>` on the manager and workers first. For mutable tags,
`swarm_init` also pulls on the manager to avoid a stale local tag differing from
the digest resolved by Swarm. A fixed digest keeps the version consistent.

Allow these ports between the nodes and, where noted, from the browser network:

| Port | Protocol | Purpose |
| --- | --- | --- |
| `2377` | TCP | Swarm cluster management |
| `7946` | TCP/UDP | Node discovery and gossip |
| `4789` | UDP | Overlay VXLAN traffic |
| `8800` | TCP | Master Web, published by `make swarm_master` |

Only `8800` needs to be reachable from the browser network. The first three
ports must be reachable between all Swarm nodes. Restrict the sources in a
production network; do not expose the Docker socket or Swarm management port to
the public Internet.

## 2. Install Docker and initialize the manager

Install and start Docker Engine on all three hosts. On Ubuntu, for example:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

Log in again so the current user has Docker access. On `swarm-manager-1`, check:

```bash
docker version
docker info
```

Initialize Swarm with an address reachable from the other nodes:

```bash
docker swarm init --advertise-addr 192.168.10.11
```

`--advertise-addr` must be the manager address that the other nodes can reach.
On multi-homed hosts, do not rely on Docker's automatic interface selection.

Check the manager:

```bash
docker node ls
docker info --format '{{.Swarm.LocalNodeState}} {{.Swarm.ControlAvailable}}'
```

The local state should be `active`, control availability should be `true`, and
the manager should be `Leader` or `Reachable` in `docker node ls`.

## 3. Join 1-2 workers

On the manager, generate the worker join command:

```bash
docker swarm join-token worker
```

Run the complete `docker swarm join --token ... 192.168.10.11:2377` command from
the output on `swarm-worker-1` and, optionally, `swarm-worker-2`. Do not run
`docker swarm init` again on a worker.

Confirm the nodes from the manager:

```bash
docker node ls
```

The result should look like this (IDs and versions will differ):

```text
ID                            HOSTNAME         STATUS  AVAILABILITY  MANAGER STATUS
... *                         swarm-manager-1  Ready   Active         Leader
...                           swarm-worker-1   Ready   Active
...                           swarm-worker-2   Ready   Active
```

Fix Docker service or node-to-node networking before continuing if a node is
`Down` or `Drain`. Tasks have no node constraint by default, so a verification
job may run on any available worker or manager. To constrain tasks, add valid
`docker service create` arguments to `launch.cluster.swarm_extra_args`.

## 4. Prepare the image, environment, and source path

On the manager that will run `make swarm_master`, change to the UCAgent source
root and set the model environment. The Makefile forwards variable names; Docker
reads their values from the current shell:

```bash
cd /path/to/UCAgent

export OPENAI_API_BASE="https://<openai-compatible-endpoint>/v1"
export OPENAI_API_KEY="<api-key>"
export OPENAI_MODEL="<model-name>"
```

For an Anthropic-compatible endpoint, set these explicitly if needed:

```bash
export ANTHROPIC_BASE_URL="$OPENAI_API_BASE"
export ANTHROPIC_AUTH_TOKEN="$OPENAI_API_KEY"
export ANTHROPIC_MODEL="$OPENAI_MODEL"
```

These variables are used when Master constructs the launch environment for child
Agents. The selected backend must be authenticated inside the child Agent container.
Logging in to a CLI on the manager host does not automatically pass that host's
login state to a Swarm job.

By default, `make swarm_master` uses the published `SWARM_IMAGE`. To run the
Master container from the current source tree, provide the source directory:

```bash
make swarm_master UCAGENT_MASTER_SOURCE=/path/to/UCAgent
```

The directory is mounted as `/UCAgent` and Master starts with
`python3 /UCAgent/ucagent/cli.py`. The Master service is constrained to a
manager, so this path must exist on that manager; it is not copied to workers.
The image must also contain Python dependencies compatible with the current
source. An older image with newer source can repeatedly restart due to missing
modules. Do not set this variable when using the published image.

## 5. Start Swarm Master Web

Run this on the manager:

```bash
make swarm_master
```

The target will:

1. Check the Docker CLI, curl, daemon, socket, active Swarm state, and manager access.
2. Create the attachable `overlay` network `ucagent_net`, or validate the driver/scope of an existing network.
3. Pull `SWARM_IMAGE` for every mutable tag, or when a fixed digest is not present locally.
4. Create a single-replica `ucagent_master` service constrained to a manager.
5. Mount `/var/run/docker.sock` and `SWARM_MASTER_PERSIST` into the Master container.
6. Listen on `0.0.0.0:8800` and override the default task launch mode to `docker_swarm`.

`make swarm_master` waits for both a 1/1 service and a response from the Master
API at the browser address. If it fails, inspect `docker service ps` and
`docker service logs` for startup errors.

Common Make targets and variables:

| Target or variable | Default | Description |
| --- | --- | --- |
| `swarm_check` | - | Check Docker, the socket, active Swarm state, and manager access |
| `swarm_init` | - | Run `swarm_check`, create the overlay network, and ensure the Master image exists |
| `swarm_master` | - | Create or recreate the Master service |
| `swarm_clean` | - | Remove services and stop running containers matching `ucagent` |
| `SWARM_IMAGE` | `ghcr.nju.edu.cn/xs-mlvp/ucagent:latest` | Image used by Master and child Agents |
| `SWARM_NETWORK` | `ucagent_net` | Name of the attachable overlay network |
| `SWARM_MASTER_SERVICE` | `ucagent_master` | Master service name and internal callback address |
| `SWARM_MASTER_PORT` | `8800` | Published Master Web port |
| `SWARM_MASTER_PERSIST` | `/tmp/ucagent_master` | Persistent directory on the manager |
| `SWARM_MASTER_HOST` | Auto-detected | Hostname or IP used for the HTTP readiness check and browser access |
| `SWARM_MASTER_WAIT_SECONDS` | `300` | Positive integer seconds to wait for a 1/1 service and a responding Master API |
| `SWARM_DOCKER_SOCK` | `/var/run/docker.sock` | Docker socket used to create child Agent services |
| `UCAGENT_MASTER_SOURCE` | Empty | Optional manager source tree mounted at `/UCAgent` |
| `ARGS` | Empty | Additional UCAgent arguments appended to the Master CLI |

The default persistent directory is `/tmp/ucagent_master` on the manager. For a
long-running deployment, use a dedicated directory:

```bash
sudo mkdir -p /srv/ucagent/master
sudo chown "$USER" /srv/ucagent/master

make swarm_master \
  SWARM_MASTER_PERSIST=/srv/ucagent/master \
  SWARM_MASTER_HOST=192.168.10.11
```

`SWARM_MASTER_HOST` is used for the HTTP readiness check and the browser address
printed at the end. Set it to a manager IP or DNS name reachable from both the
host running Make and the browser. When Colima uses host publishing, it defaults
to `127.0.0.1`; set it explicitly for a remote Docker context or another network
topology. Master and child Agents
use the overlay service name `ucagent_master:8800` internally, so do not use
`SWARM_MASTER_HOST` as the internal child-Agent address.

Append `ARGS` when the default backend or another CLI option must be changed:

```bash
make swarm_master \
  SWARM_MASTER_HOST=192.168.10.11 \
  ARGS="--override launch.default_args.backend=codex --override launch.default_args.mcp_server_no_file_tools=True"
```

Non-LangChain backends such as `codex` communicate with child Agents through MCP. This enables MCP without exposing file tools.

On success, the command prints two kinds of address:

- `http://ucagent_master:8800` works only for containers on the overlay network.
- `http://192.168.10.11:8800` is the browser address; use the actual manager address printed by the command.

Open the browser address. The Launch page will have `Docker Swarm` selected by
default. Create a workspace, upload RTL, complete Compile, and click
**Launch Task** to create a Swarm job named like `ucagent-<task-id>`. The child
Agent registers with Master through `ucagent_master:8800`; the image and overlay
network must be available on the node that receives the job.

## 6. Inspect services and tasks

Inspect Master from the manager:

```bash
docker service ls
docker service ps ucagent_master --no-trunc
docker service logs -f ucagent_master
```

After Master Web starts a task, use the service name shown in the task details:

```bash
docker service ls --filter name=ucagent-
docker service ps ucagent-<task-id> --no-trunc
docker service logs -f ucagent-<task-id>
```

If a task does not reach running, inspect the full `docker service ps` error,
then check that the target node can pull `SWARM_IMAGE`, reach the overlay
network, and use the workspace sync and mount settings. The Task page also keeps
stdout/stderr and the Swarm service state.

A 1/1 service and a registered child Agent establish the deployment path only.
For end-to-end acceptance, confirm stage progression, final completion status,
and the actual tests and reports in the workspace.

## 7. Update, stop, and clean up

Running `make swarm_master` again removes and recreates the service with the same
name; the persistent directory is not removed. To remove only this walkthrough's
task and Master services:

```bash
docker service rm ucagent-<task-id>
docker service rm ucagent_master
```

Remove UCAgent services and stop matching running containers with:

```bash
make swarm_clean
```

`swarm_clean` matches `ucagent` against entire service and container list rows,
including image names. Check the result first when other projects share the
Docker daemon.

When the test cluster is no longer needed, leave it from each node:

```bash

# worker nodes
docker swarm leave

# finally the manager; a single-manager cluster needs --force
docker swarm leave --force
```

## 8. Troubleshooting

### `make swarm_master` says that Swarm is not active

Run `docker info` and `docker node ls` on the current Docker context. The target
must run on an active manager; a worker cannot create the Master service.

### The overlay network exists with the wrong type

The Makefile requires `ucagent_net` to use driver `overlay` and scope `swarm`:

```bash
docker network inspect ucagent_net
```

Remove it or choose another name before retrying:

```bash
make swarm_master SWARM_NETWORK=ucagent_verification_net
```

### Master Web opens but a Launch task cannot start

Confirm that every schedulable node can pull `SWARM_IMAGE` and that the Master
service has a usable Docker socket:

```bash
docker service ps ucagent_master --no-trunc
docker service logs ucagent_master
```

If `UCAGENT_MASTER_SOURCE` is set, confirm that the manager path still exists.
For extra local tools or directories, declare `extra_mounts` in the Launch cluster
configuration and make the source path identical on every possible task node.

### The child Agent registers but verification stages do not advance

Inspect the Task page output and the selected backend's authentication inside
the child Agent container. Confirm that the model variables or credentials are
actually available to the job. A running Master Web or 1/1 Swarm service does
not establish that a model call or stage validation has completed.

### The browser cannot reach the printed address

Rerun with a manager address reachable from the browser:

```bash
make swarm_master SWARM_MASTER_HOST=<browser-reachable-manager-ip-or-dns>
```

Check host firewall and cloud security rules for TCP `8800`. `127.0.0.1` works
only when the browser and Docker manager are on the same host.
