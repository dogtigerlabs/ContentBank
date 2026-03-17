.PHONY: install dev validate generate test lint fmt run

PYTHON  = .venv/bin/python3
PIP     = .venv/bin/pip
PYTEST  = .venv/bin/pytest
RUFF    = .venv/bin/ruff

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install:
	python3 -m venv .venv
	$(PIP) install -e ".[dev]"

# ---------------------------------------------------------------------------
# Build pipeline: validate shapes → generate schemas
# ---------------------------------------------------------------------------

validate:
	$(PYTHON) -c "\
from pyshacl import validate; \
from rdflib import Graph; \
import pathlib; \
g = Graph(); \
[g.parse(str(f)) for f in pathlib.Path('shapes').rglob('*.ttl')]; \
print(f'Shapes loaded: {len(g)} triples — no syntax errors')"

generate: validate
	$(PYTHON) tools/schema_gen/generate.py --shapes shapes --out generated/schemas
	@echo "Generated schemas written to generated/schemas/"

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

run:
	CB_NODE_ID=urn:cb:node:00000000-0000-0000-0000-000000000001 \
	CB_DEBUG=true \
	$(PYTHON) -m contentbank.main

test:
	$(PYTEST) tests/ -v --cov=src/contentbank --cov-report=term-missing

lint:
	$(RUFF) check src/ tools/ tests/

fmt:
	$(RUFF) format src/ tools/ tests/
