PYTHON ?= python3
PYCACHE_PREFIX ?= /tmp/pycache

.PHONY: test compile check schema-check package-check

test:
	PYTHONPYCACHEPREFIX=$(PYCACHE_PREFIX) $(PYTHON) -m unittest tests.test_deepplan tests.test_deepplan_server tests.test_deepplan_client tests.test_contracts

compile:
	PYTHONPYCACHEPREFIX=$(PYCACHE_PREFIX) $(PYTHON) -m py_compile deepplan.py deepplan_store.py deepplan_agent.py deepplan_server.py deepplan_client.py deepplan_sdk/__init__.py deepplan_sdk/client.py examples/deepplan_kernel_adapter.py examples/deepplan_planner_host.py tests/test_deepplan.py tests/test_deepplan_server.py tests/test_deepplan_client.py tests/test_contracts.py

check: compile test

schema-check:
	$(PYTHON) deepplan.py schema --check

package-check:
	PYTHONPYCACHEPREFIX=$(PYCACHE_PREFIX) $(PYTHON) -m py_compile deepplan_sdk/__init__.py deepplan_sdk/client.py
