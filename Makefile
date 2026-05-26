
# Current Workspace Dir
CWD ?= output/workspace_$*
CFG ?= config.yaml
BBV ?= false
SRC ?= examples
SWARM_IMAGE ?= ghcr.nju.edu.cn/xs-mlvp/ucagent:latest
SWARM_NETWORK ?= ucagent_net
SWARM_MASTER_SERVICE ?= ucagent_master
SWARM_MASTER_PORT ?= 8800
SWARM_MASTER_PERSIST ?= /tmp/ucagent_master
SWARM_DOCKER_SOCK ?= /var/run/docker.sock
SWARM_LOCAL_UCAGENT_DIR := $(CURDIR)
MASTER_IP ?= 127.0.0.1

ifneq ($(strip $(UCAGENT_MASTER_SOURCE)),)
SWARM_MASTER_SOURCE_DIR := $(abspath $(UCAGENT_MASTER_SOURCE))
SWARM_MASTER_UCAGENT_MOUNT := --mount type=bind,source=$(SWARM_MASTER_SOURCE_DIR),target=/UCAgent
SWARM_MASTER_CMD := python3 /UCAgent/ucagent/cli.py
SWARM_MASTER_SOURCE_ENV := --env UCAGENT_MASTER_SOURCE=$(SWARM_MASTER_SOURCE_DIR)
else
SWARM_MASTER_SOURCE_DIR :=
SWARM_MASTER_UCAGENT_MOUNT :=
SWARM_MASTER_CMD := ucagent
SWARM_MASTER_SOURCE_ENV := --env UCAGENT_MASTER_SOURCE=
endif

UCAGENT_PY := $(wildcard ucagent.py)
ifdef UCAGENT_PY
CMD ?= python3 ucagent.py
else
CMD ?= ucagent
endif

all: clean test

init:
	pip3 install -r requirements.txt

reset_%:
	rm $(CWD)/unity_test -rf  || true
	rm $(CWD)/.ucagent -rf  || true
	rm $(CWD)/uc_test_report -rf  || true
	rm $(CWD)/*.md -rf  || true

init_%:
	mkdir -p $(CWD)/$*_RTL
	cp $(SRC)/$*/*.v $(CWD)/$*_RTL/ || true
	cp $(SRC)/$*/*.sv $(CWD)/$*_RTL/ || true
	cp $(SRC)/$*/*.vh $(CWD)/$*_RTL/ || true
	cp $(SRC)/$*/*.scala $(CWD)/$*_RTL/ || true
	cp $(SRC)/$*/filelist.txt $(CWD)/$*_RTL/ || true
	@if [ ! -d $(CWD)/$* ]; then \
		option_fs=""; \
		if [ -f $(CWD)/$*_RTL/filelist.txt ]; then \
			option_fs="--fs $(CWD)/$*_RTL/filelist.txt"; \
		fi; \
		if [ -f $(CWD)/$*_RTL/$*.v ]; then \
			picker export $(CWD)/$*_RTL/$*.v --rw 1 --sname $* --tdir $(CWD)/ -c -w $(CWD)/$*/$*.fst $$option_fs; \
		elif [ -f $(CWD)/$*_RTL/$*.sv ]; then \
			picker export $(CWD)/$*_RTL/$*.sv --rw 1 --sname $* --tdir $(CWD)/ -c -w $(CWD)/$*/$*.fst $$option_fs; \
		fi; \
	fi
	cp $(SRC)/$*/*.md $(CWD)/$*/  || true
	cp $(SRC)/$*/*.py $(CWD)/$*/  || true
	@if [ $(BBV) = "true" ]; then \
		echo "Enable BBV mode: clear RTL files"; \
		for f in $(CWD)/$*/$*.v $(CWD)/$*/$*.sv $(CWD)/$*/$*.vh; do \
			if [ -f $$f ]; then \
				echo "clear file $$f"; \
				echo "" > $$f; \
			fi; \
		done; \
		for f in `find $(CWD)/$*_RTL/*|grep -v '.scala'`; do \
			echo "" > $$f; \
		done; \
	fi
	@python3 $(CWD)/$*/example.py || { echo "Error: picker try to generate DUT, but failed.\n"; exit 1; }

test_%: init_%
	$(CMD) $(CWD)/ $* --config $(CFG) -s -hm --tui -l ${ARGS}

test_with_master_%: init_%
	$(CMD) $(CWD)/ $* --config $(CFG) -s -hm --tui -l --master ${MASTER_IP} --export-cmd-api  ${ARGS}

mcp_%: init_%
	$(CMD) $(CWD)/ $* --config $(CFG) -s -hm --tui --mcp-server-no-file-tools ${ARGS}

mcp_with_master_%: init_%
	$(CMD) $(CWD)/ $* --config $(CFG) -s -hm --tui --mcp-server-no-file-tools --master ${MASTER_IP} --export-cmd-api ${ARGS}

mcp_all_tools_%: init_%
	$(CMD) $(CWD)/ $* --config $(CFG) -s -hm --tui --mcp-server ${ARGS}

clean_%:
	rm -rf $(CWD)

clean:
	rm -rf .pytest_cache
	rm -rf UCAgent.egg-info
	rm -rf build
	rm -rf dist
	find ./ -name '*.dat'|xargs rm -f
	find ./ -name '*.vcd'|xargs rm -f
	find ./ -name '*.fst'|xargs rm -f
	find ./ -name __pycache__|xargs rm -rf
	find ./ -name output|xargs rm -rf

clean_test_%:
	rm -rf $(CWD)/unity_test

continue_%:
	$(CMD) $(CWD)/ ${DUT} --config config.yaml ${ARGS}

as_master:
	$(CMD) --as-master ${ARGS}

as_master_persist:
	$(CMD) --as-master-persist ${PATH_PERSISTENT} --as-master ${ARGS}

swarm_check:
	@command -v docker >/dev/null 2>&1 || { echo "Error: docker CLI is not installed or not in PATH."; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "Error: Docker daemon is not available. Please start Docker first."; exit 1; }
	@test -S $(SWARM_DOCKER_SOCK) || { echo "Error: Docker socket $(SWARM_DOCKER_SOCK) is not available."; exit 1; }
	@if [ -n "$(SWARM_MASTER_SOURCE_DIR)" ] && [ ! -f "$(SWARM_MASTER_SOURCE_DIR)/ucagent/cli.py" ]; then \
		echo "Error: UCAGENT_MASTER_SOURCE must point to a UCAgent source tree containing ucagent/cli.py: $(SWARM_MASTER_SOURCE_DIR)"; \
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

swarm_init:
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
	docker image inspect $(SWARM_IMAGE) 1>/dev/null

swarm_master: swarm_init
	@mkdir -p $(SWARM_MASTER_PERSIST)
	@if docker service inspect $(SWARM_MASTER_SERVICE) >/dev/null 2>&1; then \
		echo "Removing existing Docker Swarm service $(SWARM_MASTER_SERVICE)..."; \
		docker service rm $(SWARM_MASTER_SERVICE) >/dev/null; \
		while docker service inspect $(SWARM_MASTER_SERVICE) >/dev/null 2>&1; do sleep 1; done; \
	fi
	docker service create \
		--name $(SWARM_MASTER_SERVICE) \
		--hostname $(SWARM_MASTER_SERVICE) \
		--detach=true \
		--replicas 1 \
		--restart-condition any \
		--constraint node.role==manager \
		--network $(SWARM_NETWORK) \
		--env DOCKER_HOST=unix://$(SWARM_DOCKER_SOCK) \
		$(SWARM_MASTER_SOURCE_ENV) \
		--publish published=$(SWARM_MASTER_PORT),target=$(SWARM_MASTER_PORT) \
		--mount type=bind,source=$(abspath $(SWARM_MASTER_PERSIST)),target=$(SWARM_MASTER_PERSIST) \
		--mount type=bind,source=$(SWARM_DOCKER_SOCK),target=$(SWARM_DOCKER_SOCK) \
		$(SWARM_MASTER_UCAGENT_MOUNT) \
		--workdir /workspace/ucagent \
		$(SWARM_IMAGE) \
		sh -c 'tail -f /dev/null | $(SWARM_MASTER_CMD) --as-master-persist $(SWARM_MASTER_PERSIST) --as-master 0.0.0.0:$(SWARM_MASTER_PORT) $(ARGS)'
	@echo "Waiting for $(SWARM_MASTER_SERVICE) to start..."
	@for i in $$(seq 1 30); do \
		replicas=$$(docker service ls --filter name=$(SWARM_MASTER_SERVICE) --format '{{.Replicas}}' | head -n 1); \
		if [ "$$replicas" = "1/1" ]; then \
			echo "Docker Swarm master is running: http://$(SWARM_MASTER_SERVICE):$(SWARM_MASTER_PORT) on network $(SWARM_NETWORK)"; \
			echo "Published on host: http://127.0.0.1:$(SWARM_MASTER_PORT)"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Error: Docker Swarm service $(SWARM_MASTER_SERVICE) did not reach 1/1 replicas."; \
	echo "Hint: inspect it with: docker service ps $(SWARM_MASTER_SERVICE) --no-trunc"; \
	echo "Hint: view logs with: docker service logs $(SWARM_MASTER_SERVICE)"; \
	exit 1

# Include docs Makefile
-include docs/Makefile

# ---------- Formal Verification ----------
FORMAL_DIR   := examples/Formal
FORMAL_CWD   ?= $(FORMAL_DIR)/output/workspace_$*
FORMAL_CFG   := ucagent/lang/zh/config/formal.yaml
FORMAL_DOC   := ucagent/lang/zh/doc/Formal_Doc

formal_init_%:
	mkdir -p $(FORMAL_CWD)
	cp -r $(FORMAL_DIR)/$* $(FORMAL_CWD)/

formal_%: formal_init_%
	$(CMD) $(FORMAL_CWD)/ $* --config $(FORMAL_CFG) -s -hm --tui --guid-doc-path $(FORMAL_DOC)/ --output formal_test $(ARGS)

formal_mcp_%: formal_init_%
	$(CMD) $(FORMAL_CWD)/ $* --config $(FORMAL_CFG) -s -hm --tui --mcp-server-no-file-tools --guid-doc-path $(FORMAL_DOC)/ --output formal_test --mcp-server-port 5000 --master 127.0.0.1 --export-cmd-api --use-skill --log $(ARGS)

clean_formal:
	rm -rf $(FORMAL_DIR)/output
