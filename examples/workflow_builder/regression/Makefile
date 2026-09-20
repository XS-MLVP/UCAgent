.PHONY: all contract stability checker_descriptions requirement_templates living_plan write_boundaries evaluation_split review_ui documentation environment_setup

PYTHON ?= python3
ROOT := $(abspath ..)

all: contract stability checker_descriptions requirement_templates living_plan write_boundaries evaluation_split review_ui documentation environment_setup

contract:
	cd $(ROOT) && PYTHONPATH="$(abspath $(ROOT)/../..):$${PYTHONPATH:-}" $(PYTHON) regression/run_delivery_contract_regression.py

stability:
	cd $(ROOT) && PYTHONPATH="$(abspath $(ROOT)/../..):$${PYTHONPATH:-}" $(PYTHON) regression/run_builder_stability_regression.py

checker_descriptions:
	cd $(ROOT) && PYTHONPATH="$(abspath $(ROOT)/../..):$${PYTHONPATH:-}" $(PYTHON) regression/run_checker_description_regression.py

requirement_templates:
	cd $(ROOT) && PYTHONPATH="$(abspath $(ROOT)/../..):$${PYTHONPATH:-}" $(PYTHON) regression/run_requirement_template_contract_regression.py

living_plan:
	cd $(ROOT) && PYTHONPATH="$(abspath $(ROOT)/../..):$${PYTHONPATH:-}" $(PYTHON) regression/run_living_plan_regression.py

write_boundaries:
	cd $(ROOT) && PYTHONPATH="$(abspath $(ROOT)/../..):$${PYTHONPATH:-}" $(PYTHON) regression/run_write_boundary_regression.py

evaluation_split:
	cd $(ROOT) && PYTHONPATH="$(abspath $(ROOT)/../..):$${PYTHONPATH:-}" $(PYTHON) regression/run_evaluation_split_regression.py

review_ui:
	cd $(ROOT) && PYTHONPATH="$(abspath $(ROOT)/../..):$${PYTHONPATH:-}" $(PYTHON) regression/run_review_ui_regression.py

documentation:
	cd $(ROOT) && $(PYTHON) regression/run_documentation_regression.py

environment_setup:
	cd $(ROOT) && $(PYTHON) regression/run_environment_setup_regression.py
