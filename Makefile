PYTHON ?= python3
PYCACHE_PREFIX ?= /tmp/pycache

.PHONY: test compile check schema-check

test:
	PYTHONPYCACHEPREFIX=$(PYCACHE_PREFIX) $(PYTHON) -m unittest tests.test_deepplan tests.test_deepplan_server tests.test_deepplan_client

compile:
	PYTHONPYCACHEPREFIX=$(PYCACHE_PREFIX) $(PYTHON) -m py_compile deepplan.py deepplan_store.py deepplan_agent.py deepplan_server.py deepplan_client.py tests/test_deepplan.py tests/test_deepplan_server.py tests/test_deepplan_client.py

check: compile test

schema-check:
	$(PYTHON) deepplan.py schema --check
