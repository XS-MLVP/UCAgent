# Local Master entry points and Docker Swarm deployment.

## Master and Docker Swarm
# Deployment settings
SWARM_IMAGE ?= ghcr.nju.edu.cn/xs-mlvp/ucagent:latest
SWARM_NETWORK ?= ucagent_net
SWARM_MASTER_SERVICE ?= ucagent_master
SWARM_MASTER_PORT ?= 8800
SWARM_MASTER_PERSIST ?= /tmp/ucagent_master
SWARM_DOCKER_SOCK ?= /var/run/docker.sock
SWARM_MASTER_HOST ?=
SWARM_LOCAL_UCAGENT_DIR := $(CURDIR)
SWARM_IS_COLIMA ?= $(shell ctx="$$(docker context show 2>/dev/null)"; host="$$(docker context inspect "$$ctx" --format '{{.Endpoints.docker.Host}}' 2>/dev/null)"; printf '%s\n%s\n' "$$ctx" "$$host" | grep -Eq '(^colima|[/.]colima)' && echo 1 || echo 0)
SWARM_COLIMA_SSH ?= colima ssh --
SWARM_MASTER_PERSIST_SOURCE := $(abspath $(SWARM_MASTER_PERSIST))
SWARM_COMMA := ,
MASTER_IP ?= 127.0.0.1

SWARM_MASTER_PUBLISH = published=$(SWARM_MASTER_PORT),target=$(SWARM_MASTER_PORT)$(if $(filter 1 true yes,$(SWARM_IS_COLIMA)),$(SWARM_COMMA)mode=host)
SWARM_DOCKER_SOCK_CHECK = $(if $(filter 1 true yes,$(SWARM_IS_COLIMA)),$(SWARM_COLIMA_SSH) test -S $(SWARM_DOCKER_SOCK),test -S $(SWARM_DOCKER_SOCK))
SWARM_MASTER_PERSIST_MKDIR = $(if $(filter 1 true yes,$(SWARM_IS_COLIMA)),$(SWARM_COLIMA_SSH) mkdir -p $(SWARM_MASTER_PERSIST_SOURCE),mkdir -p $(SWARM_MASTER_PERSIST_SOURCE))

ifneq ($(strip $(UCAGENT_MASTER_SOURCE)),)
SWARM_MASTER_SOURCE_DIR := $(abspath $(UCAGENT_MASTER_SOURCE))
SWARM_MASTER_UCAGENT_MOUNT := --mount type=bind,source=$(SWARM_MASTER_SOURCE_DIR),target=/UCAgent
SWARM_MASTER_CMD := python3 /UCAgent/ucagent/__main__.py
SWARM_MASTER_SOURCE_ENV := --env UCAGENT_MASTER_SOURCE=$(SWARM_MASTER_SOURCE_DIR)
else
SWARM_MASTER_SOURCE_DIR :=
SWARM_MASTER_UCAGENT_MOUNT :=
SWARM_MASTER_CMD := ucagent
SWARM_MASTER_SOURCE_ENV := --env UCAGENT_MASTER_SOURCE=
endif

SWARM_OVERRIDE := --override launch.default_args.launch_mode=docker_swarm \
                  --override launch.cluster.docker_network=$(SWARM_NETWORK) \
                  --override launch.cluster.master_ip=$(SWARM_MASTER_SERVICE)
#                 --override launch.default_args.extra_args[0:0]=@base64:LS1vdmVycmlkZQpzdGFnZVstMV0ubmVlZF9odW1hbl9jaGVjaz1UcnVl

# Forward names only; Docker obtains the values from the environment.
SWARM_FORWARD_ENV := OPENAI_MODEL OPENAI_API_KEY OPENAI_API_BASE \
                     EMBED_MODEL EMBED_OPENAI_API_KEY EMBED_OPENAI_API_BASE \
                     UC_MODEL_TYPE ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN \
                     ANTHROPIC_MODEL ANTHROPIC_BIG_MODEL ANTHROPIC_SML_MODEL \
                     GOOGLE_GENAI_API_KEY GOOGLE_GENAI_MODEL \
                     UC_ENV_CMD_BACKEND_EX_ARGS UC_ENV_CMD_BACKEND_EX_ARGS_N UC_ENV_CMD_BACKEND_EX_ARGS_C

# Local Master
as_master: ## Start the local Master service
	$(CMD) --as-master --export-cmd-api ${ARGS}

as_master_persist: ## Start Master with PATH_PERSISTENT for persistent storage
	$(CMD) --as-master-persist ${PATH_PERSISTENT}  --export-cmd-api --as-master ${ARGS}

# Swarm validation and resources
swarm_check: ## Check Docker, its socket, and Swarm manager readiness
	@command -v docker >/dev/null 2>&1 || { echo "Error: docker CLI is not installed or not in PATH."; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "Error: Docker daemon is not available. Please start Docker first."; exit 1; }
	@$(SWARM_DOCKER_SOCK_CHECK) || { echo "Error: Docker socket $(SWARM_DOCKER_SOCK) is not available."; exit 1; }
	@if [ -n "$(SWARM_MASTER_SOURCE_DIR)" ] && [ ! -f "$(SWARM_MASTER_SOURCE_DIR)/ucagent/__main__.py" ]; then \
		echo "Error: UCAGENT_MASTER_SOURCE must point to a UCAgent source tree containing ucagent/__main__.py: $(SWARM_MASTER_SOURCE_DIR)"; \
		exit 1; \
	fi
	@state=$$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null); \
	if [ "$$state" != "active" ]; then \
		echo "Error: Docker Swarm is not active (state: $${state:-unknown})."; \
		echo "Hint: initialize or join a swarm first, for example: docker swarm init"; \
		exit 1; \
	fi
	@control=$$(docker info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null); \
	if [ "$$control" != "true" ]; then \
		echo "Error: this Docker node is not a Swarm manager, so it cannot launch Swarm services."; \
		echo "Hint: run make swarm_master on a manager node, or promote this node with: docker node promote <node>"; \
		exit 1; \
	fi

swarm_init: ## Check Swarm and prepare the network and image
	$(MAKE) swarm_check
	@if docker network inspect $(SWARM_NETWORK) >/dev/null 2>&1; then \
		driver=$$(docker network inspect $(SWARM_NETWORK) --format '{{.Driver}}'); \
		scope=$$(docker network inspect $(SWARM_NETWORK) --format '{{.Scope}}'); \
		if [ "$$driver" != "overlay" ] || [ "$$scope" != "swarm" ]; then \
			echo "Error: Docker network $(SWARM_NETWORK) exists but is $$driver/$$scope, expected overlay/swarm."; \
			echo "Hint: remove or rename the existing network, then run make swarm_master again."; \
			exit 1; \
		fi; \
	else \
		docker network create --driver overlay --attachable $(SWARM_NETWORK); \
	fi
	@if ! docker image inspect $(SWARM_IMAGE) >/dev/null 2>&1; then \
		echo "Pulling Docker image $(SWARM_IMAGE)..."; \
		docker pull $(SWARM_IMAGE); \
	fi

swarm_clean: ## Remove ucagent Swarm services and stop ucagent containers
	@echo "Removing existing Docker Swarm services with name prefix $(SWARM_MASTER_SERVICE)...";
	@sid=`docker service list|grep ucagent|awk '{print $$1}'|xargs`; if [ -n "$$sid" ]; then echo "stop service $$sid"; docker service rm $$sid; fi;
	@docker service ls
	@echo "Stop all containers...";
	@did=`docker ps|grep ucagent|awk '{print $$1}'|xargs`; if [ -n "$$did" ]; then echo "stop container $$did"; docker stop $$did; fi;
	@docker ps -a

swarm_master: swarm_init ## Deploy Master as a Docker Swarm service
	@$(SWARM_MASTER_PERSIST_MKDIR)
	@if docker service inspect $(SWARM_MASTER_SERVICE) >/dev/null 2>&1; then \
		echo "Removing existing Docker Swarm service $(SWARM_MASTER_SERVICE)..."; \
		docker service rm $(SWARM_MASTER_SERVICE) >/dev/null; \
		while docker service inspect $(SWARM_MASTER_SERVICE) >/dev/null 2>&1; do sleep 1; done; \
	fi
	@docker service create \
		--name $(SWARM_MASTER_SERVICE) \
		--hostname $(SWARM_MASTER_SERVICE) \
		--detach=true \
		--replicas 1 \
		--restart-condition any \
		--constraint node.role==manager \
		--network $(SWARM_NETWORK) \
		--env DOCKER_HOST=unix://$(SWARM_DOCKER_SOCK) \
		--env UCAGENT_LAUNCH_IMAGE=$(SWARM_IMAGE) \
		--env UCAGENT_LAUNCH_MASTER_IP=$(SWARM_MASTER_SERVICE) \
		$(foreach name,$(SWARM_FORWARD_ENV),--env $(name)) \
		$(SWARM_MASTER_SOURCE_ENV) \
		--publish $(SWARM_MASTER_PUBLISH) \
		--mount type=bind,source=$(SWARM_MASTER_PERSIST_SOURCE),target=$(SWARM_MASTER_PERSIST) \
		--mount type=bind,source=$(SWARM_DOCKER_SOCK),target=$(SWARM_DOCKER_SOCK) \
		$(SWARM_MASTER_UCAGENT_MOUNT) \
		--workdir /workspace/UCAgent \
		$(SWARM_IMAGE) \
		sh -c "tail -f /dev/null | $(SWARM_MASTER_CMD) --export-cmd-api --as-master-persist $(SWARM_MASTER_PERSIST) --as-master 0.0.0.0:$(SWARM_MASTER_PORT) $(SWARM_OVERRIDE) $(ARGS)"
	@echo "Waiting for $(SWARM_MASTER_SERVICE) to start..."
	@for i in $$(seq 1 30); do \
		replicas=$$(docker service ls --filter name=$(SWARM_MASTER_SERVICE) --format '{{.Replicas}}' | head -n 1); \
		if [ "$$replicas" = "1/1" ]; then \
			host="$(SWARM_MASTER_HOST)"; \
			if [ -z "$$host" ]; then \
				host=$$(docker node inspect self --format '{{.Status.Addr}}' 2>/dev/null | head -n 1); \
			fi; \
			if [ -z "$$host" ] || [ "$$host" = "<no value>" ]; then \
				host=$$(docker info --format '{{.Swarm.NodeAddr}}' 2>/dev/null); \
			fi; \
			if [ -z "$$host" ] || [ "$$host" = "<no value>" ]; then \
				host=$$(hostname -I 2>/dev/null | awk '{print $$1}'); \
			fi; \
			if [ -z "$$host" ]; then host=127.0.0.1; fi; \
			echo "Docker Swarm master is running: http://$(SWARM_MASTER_SERVICE):$(SWARM_MASTER_PORT) on network $(SWARM_NETWORK)"; \
			echo "Published on host: http://$$host:$(SWARM_MASTER_PORT)"; \
			echo "Override the printed host with: make swarm_master SWARM_MASTER_HOST=<reachable-ip-or-dns>"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Error: Docker Swarm service $(SWARM_MASTER_SERVICE) did not reach 1/1 replicas."; \
	echo "Hint: inspect it with: docker service ps $(SWARM_MASTER_SERVICE) --no-trunc"; \
	echo "Hint: view logs with: docker service logs $(SWARM_MASTER_SERVICE)"; \
	exit 1
