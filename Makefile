.PHONY: help install install-dev lint fmt typecheck clean dist uninstall

PYTHON  ?= python3
PIP     ?= pip3
PKG     := mountbridge
VERSION := $(shell grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)

help:
	@echo ""
	@echo "  MountBridge $(VERSION)"
	@echo ""
	@echo "  make install        Install for current user via pip"
	@echo "  make install-dev    Install in editable mode + dev deps"
	@echo "  make lint           Run ruff linter"
	@echo "  make fmt            Auto-format with ruff"
	@echo "  make typecheck      Run mypy"
	@echo "  make clean          Remove build artefacts"
	@echo "  make dist           Build source + wheel distributions"
	@echo "  make uninstall      Uninstall the package"
	@echo ""

install:
	$(PIP) install --user --break-system-packages .

install-dev:
	$(PIP) install --user --break-system-packages -e ".[dev]"

lint:
	ruff check $(PKG)/

fmt:
	ruff check --fix $(PKG)/
	ruff format $(PKG)/

typecheck:
	mypy $(PKG)/ --ignore-missing-imports

clean:
	rm -rf dist/ build/ *.egg-info $(PKG)/__pycache__ $(PKG)/**/__pycache__

dist: clean
	$(PYTHON) -m build

uninstall:
	$(PIP) uninstall -y $(PKG)
