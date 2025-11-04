PYTHON ?= python3

VENV_DIR := virt-py
VENV_PIP := $(VENV_DIR)/bin/pip3
VENV_PY := $(VENV_DIR)/bin/python3

.PHONY: run build format check-fmt check-lint prepare-env

prepare-env:
	@if [ ! -d "virt-py" ]; then \
		$(PYTHON) -m venv virt-py --copies; \
		$(VENV_PIP) install -r requirements.txt; \
	else \
		echo "Virtual environment 'virt-py' already exists"; \
	fi

build: prepare-env
	$(VENV_PY) -m build

run: prepare-env
	$(VENV_PY) bot.py

format: prepare-env
	$(VENV_PY) -m black bot.py src/

check-fmt: prepare-env
	$(VENV_PY) -m black --check bot.py src/

check-lint: prepare-env
	$(VENV_PY) -m pylint bot.py $$(find src -type f -name "*.py")
