export PYTHONPATH := $(CURDIR)/src$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: validate test package

validate:
	ucagent --validate-plugin .

test:
	python3 -m pytest -q

package:
	python3 -m build .
