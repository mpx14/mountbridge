.PHONY: help install install-dev lint fmt typecheck test check clean dist uninstall

PYTHON  ?= python3
VENV    ?= .venv
# Use the dev venv's tools when it exists, so `make check` works without activating it.
PY      := $(if $(wildcard $(VENV)/bin/python3),$(VENV)/bin/python3,$(PYTHON))
RUFF    := $(if $(wildcard $(VENV)/bin/ruff),$(VENV)/bin/ruff,ruff)
MYPY    := $(if $(wildcard $(VENV)/bin/mypy),$(VENV)/bin/mypy,mypy)
PKG     := mountbridge
LINT    := $(PKG)/ tests/ data/mountbridge-helper
VERSION := $(shell grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)

help:
	@echo ""
	@echo "  MountBridge $(VERSION)"
	@echo ""
	@echo "  make install        Install for current user via pipx"
	@echo "  make install-dev    Create $(VENV) (sees apt's python3-gi) with dev deps"
	@echo "  make lint           Run ruff"
	@echo "  make fmt            Auto-format with ruff"
	@echo "  make typecheck      Run mypy"
	@echo "  make test           Run pytest"
	@echo "  make check          lint + test (what CI runs)"
	@echo "  make clean          Remove build artefacts"
	@echo "  make dist           Build source + wheel distributions"
	@echo "  make uninstall      Uninstall the package"
	@echo ""

install:
	pipx install --force --system-site-packages .

install-dev:
	$(PYTHON) -m venv --system-site-packages $(VENV)
	$(VENV)/bin/pip install -e ".[dev]"

lint:
	$(RUFF) check $(LINT)

fmt:
	$(RUFF) check --fix $(LINT)
	$(RUFF) format $(LINT)

typecheck:
	$(MYPY) $(PKG)/ --ignore-missing-imports

test:
	$(PY) -m pytest -q

check: lint test

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

dist: clean
	$(PY) -m build

uninstall:
	pipx uninstall $(PKG)
