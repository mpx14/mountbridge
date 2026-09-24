.PHONY: help install install-dev lint fmt typecheck test check clean dist deb uninstall

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
	@echo "  make deb            Build dist/mountbridge_$(VERSION)_all.deb"
	@echo "                      (first: sudo apt-get build-dep ./)"
	@echo "  make uninstall      Uninstall the package"
	@echo ""

install:
	-pipx uninstall $(PKG) 2>/dev/null
	pipx install --system-site-packages .

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
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache .pybuild
	rm -rf debian/.debhelper debian/mountbridge debian/files debian/*.substvars \
		debian/*.debhelper debian/*.debhelper.log debian/debhelper-build-stamp
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

dist: clean
	$(PY) -m build

deb:
	dpkg-buildpackage -us -uc -b
	mkdir -p dist
	mv ../mountbridge_$(VERSION)_all.deb dist/
	rm -f ../mountbridge_$(VERSION)_*.buildinfo ../mountbridge_$(VERSION)_*.changes
	@echo "Built dist/mountbridge_$(VERSION)_all.deb"

uninstall:
	pipx uninstall $(PKG)
