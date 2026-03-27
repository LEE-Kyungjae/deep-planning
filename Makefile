PYTHON ?= python3
PYCACHE_PREFIX ?= /tmp/pycache

.PHONY: test compile check

test:
	PYTHONPYCACHEPREFIX=$(PYCACHE_PREFIX) $(PYTHON) -m unittest tests.test_deepplan tests.test_deepplan_server

compile:
	PYTHONPYCACHEPREFIX=$(PYCACHE_PREFIX) $(PYTHON) -m py_compile deepplan.py deepplan_store.py deepplan_agent.py deepplan_server.py tests/test_deepplan.py tests/test_deepplan_server.py

check: compile test
