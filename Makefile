.PHONY: help install install-dev lint fmt typecheck test check clean dist uninstall

PYTHON  ?= python3
VENV    ?= .venv
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
	ruff check $(LINT)

fmt:
	ruff check --fix $(LINT)
	ruff format $(LINT)

typecheck:
	mypy $(PKG)/ --ignore-missing-imports

test:
	$(PYTHON) -m pytest -q

check: lint test

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

dist: clean
	$(PYTHON) -m build

uninstall:
	pipx uninstall $(PKG)
