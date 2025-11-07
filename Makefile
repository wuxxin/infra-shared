# makefile
ROOTDIR := $(patsubst %/,%,$(dir $(realpath $(firstword $(MAKEFILE_LIST)))))
.DEFAULT_GOAL := help
_CONTAINER_CMD := $(shell test -z "$$CONTAINER_CMD" && echo "podman" || echo "$$CONTAINER_CMD")
PULUMI := pulumi --logtostderr --logflow --non-interactive
PULUMI_INTERACTIVE := pulumi --logtostderr --logflow
define BROWSER_PYSCRIPT
import os, webbrowser, sys, urllib.request
webbrowser.open("file://" + urllib.request.pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT
BROWSER := python -c "$$BROWSER_PYSCRIPT"

# skip annoying version information
PULUMI_SKIP_UPDATE_CHECK=true
PULUMI_DIY_BACKEND_GZIP=true

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' | sort

.PHONY: provision-local
provision-local: ## Build dependencies for provisioning using system apps
	@echo "+++ $@"
	if ! ./scripts/requirements.sh --check; then \
		./scripts/requirements.sh --install && \
		./scripts/requirements.sh --install-extra $(args); \
	fi
	./scripts/requirements.sh --check --verbose

.PHONY: provision-container
provision-container: ## Build dependencies for provisioning using a container
	@echo "+++ $@"
	$(_CONTAINER_CMD) build -t provision-client:latest \
		-f Containerfile/provision-client/Containerfile \
		Containerfile/provision-client

uv.lock: pyproject.toml provision-local
	@echo "+++ $@"
	uv lock

.venv/bin/activate: uv.lock
	@echo "+++ $@"
	if test -d .venv; then rm -rf .venv; fi
	uv venv

.venv/installed: .venv/bin/activate
	@echo "+++ $@"
	. .venv/bin/activate && uv sync --all-extras
	touch $@

.PHONY: buildenv
buildenv: .venv/installed ## Build python environment

.PHONY: py-clean
py-clean: ## Remove python related artifacts
	@echo "+++ $@"
	find . -type d -name '__pycache__' -exec rm -rf {} +
	find . -type d -name '.ipynb_checkpoints' -exec rm -rf {} +
	find . -type f -name '*.py[co]' -exec rm -f {} +

.PHONY: buildenv-clean
buildenv-clean: py-clean ## Remove build environment artifacts
	@echo "+++ $@"
	if test -e .venv; then rm -rf .venv; fi
	if test -e infra_shared.egg-info; then rm -rf infra_shared.egg-info; fi

.PHONY: pytest
pytest: buildenv ## Run python Tests using "pytest $(args)"
	@echo "+++ $@"
	mkdir -p build/tests/
	. .venv/bin/activate && pytest $(args)

.PHONY: pytest-clean
pytest-clean: ## Remove pytest Artifacts
	@echo "+++ $@"
	if test -d $(ROOTDIR)/build/tests; then rm -rf $(ROOTDIR)/build/tests; fi

.PHONY: sim__
sim__: ## Run "pulumi $(args)"
	@echo "+++ $@"
	cd $(ROOTDIR)/build/test_sim &&	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI_INTERACTIVE) $(args)

.PHONY: docs
docs: buildenv ## Build docs for local usage
	@echo "+++ $@"
	mkdir -p build/docs-local
	. .venv/bin/activate && mkdocs build --no-directory-urls -d build/docs-local -f mkdocs.yml
	@echo "Finished. Browse at file:///$(ROOTDIR)/build/docs-local/index.html"

.PHONY: docs-online-build
docs-online-build: buildenv ## Build docs for http serve
	@echo "+++ $@"
	mkdir -p build/docs-online
	. .venv/bin/activate && mkdocs build -d build/docs-online -f mkdocs.yml
	@echo "Finished. serve with"
	@echo ". .venv/bin/activate && python -m http.server --directory build/docs-online"

.PHONY: docs-serve
docs-serve: buildenv ## Rebuild and serve docs with autoreload
	@echo "+++ $@"
	. .venv/bin/activate && mkdocs serve -f mkdocs.yml

.PHONY: docs-clean
docs-clean: ## Remove all generated docs
	@echo "+++ $@"
	rm -rf build/docs-local build/docs-online

.PHONY: clean
clean: pytest-clean docs-clean buildenv-clean  ## Remove all artifacts
	@echo "+++ $@"
	rm -rf build

.PHONY: test-all
test-all: docs-online-build pytest ## Run all tests using local build deps
	@echo "+++ $@"

.PHONY: test-all-container
test-all-container: provision-container ## Run all tests using container build deps
	@echo "+++ $@"
	./scripts/provision_shell.sh make test-all-local

