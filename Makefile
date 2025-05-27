# makefile
ROOTDIR := $(dir $(realpath $(firstword $(MAKEFILE_LIST))))
.DEFAULT_GOAL := help
_CONTAINER_CMD := $(shell test -z "$$CONTAINER_CMD" && echo "podman" || echo "$$CONTAINER_CMD")
PULUMI := pulumi --logtostderr --logflow --non-interactive
define BROWSER_PYSCRIPT
import os, webbrowser, sys, urllib.request
webbrowser.open("file://" + urllib.request.pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT
BROWSER := python -c "$$BROWSER_PYSCRIPT"

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' | sort

.PHONY: provision-local
provision-local: ## Build dependencies for provisioning using system apps
	@echo "+++ $@"
	@if ! ./scripts/requirements.sh --check; then ./scripts/requirements.sh --install && ./scripts/requirements.sh --install-extra; fi
	@./scripts/requirements.sh --check --verbose

.PHONY: provision-container
provision-container: ## Build dependencies for provisioning using a provision-client container
	@echo "+++ $@"
	@$(_CONTAINER_CMD) build -t provision-client:latest -f Containerfile/provision-client/Containerfile Containerfile/provision-client

uv.lock: pyproject.toml provision-local
	@echo "+++ $@"
	@uv lock

.venv/bin/activate: uv.lock
	@echo "+++ $@"
	@if test -d .venv; then rm -rf .venv; fi
	@uv venv
	@uv sync --all-extras

.PHONY: build-env
build-env: .venv/bin/activate ## Build python environment

.PHONY: py-clean
py-clean: ## Remove python related artifacts
	@echo "+++ $@"
	@find . -type d -name '__pycache__' -exec rm -rf {} +
	@find . -type d -name '.ipynb_checkpoints' -exec rm -rf {} +
	@find . -type f -name '*.py[co]' -exec rm -f {} +

.PHONY: build-env-clean
build-env-clean: py-clean ## Remove build environment artifacts
	@echo "+++ $@"
	@rm -rf .venv

.PHONY: test-scripts
test-scripts: build-env ## Run script Tests
	@echo "+++ $@"
	@uv run scripts/test_serve_once.py

.PHONY: test-sim
test-sim: build-env ## Run sim up Tests
	@echo "+++ $@"
	@mkdir -p $(ROOTDIR)build/pulumi $(ROOTDIR)build/tests
	@git init $(ROOTDIR)build/tests
	@./scripts/create_skeleton.sh --project-dir $(ROOTDIR)build/tests --name-library infra --yes
	@f=$(ROOTDIR)build/tests/infra && if test ! -e $$f; then ln -s "../../" $$f; fi
	@sed -i -r "s#virtualenv: .venv#virtualenv: ../../.venv#g" $(ROOTDIR)build/tests/Pulumi.yaml
	@cd $(ROOTDIR)build/tests && $(PULUMI) login file://$(ROOTDIR)build/pulumi
	@cd $(ROOTDIR)build/tests && PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack init sim --secrets-provider passphrase
	@cd $(ROOTDIR)build/tests && PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack "select" "sim"
	@cd $(ROOTDIR)build/tests && PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) up --stack "sim" --suppress-outputs --yes $(args)

.PHONY: test-sim-clean
test-sim-clean: ## Remove Application Artifacts
	@echo "+++ $@"
	@if test -d $(ROOTDIR)build/tests; then cd $(ROOTDIR)build/tests && PULUMI_CONFIG_PASSPHRASE="sim" PULUMI_CONTINUE_ON_ERROR=true $(PULUMI) destroy --stack "sim" --yes || true; fi
	@if test -d $(ROOTDIR)build/tests; then cd $(ROOTDIR)build/tests && PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack rm "sim" --force --yes  || true; fi
	@rm -rf $(ROOTDIR)build/tests $(ROOTDIR)build/pulumi/.pulumi/backups/sim $(ROOTDIR)build/pulumi/.pulumi/history/sim || true

.PHONY: docs
docs: build-env ## Build docs for local usage and open in browser
	@echo "+++ $@"
	@mkdir -p build/docs
	@uv run mkdocs build --no-directory-urls -d build/docs-local -f mkdocs.yml
	@echo "finished. browse documentation at build/docs-local/index.html"
	@$(BROWSER) build/docs-local/index.html

.PHONY: docs-online-build
docs-online-build: build-env ## Build docs for http serve
	@echo "+++ $@"
	@mkdir -p build/docs-online
	@uv run mkdocs build -d build/docs-online -f mkdocs.yml

.PHONY: docs-serve
docs-serve: build-env ## Rebuild and serve docs with autoreload
	@echo "+++ $@"
	@uv run mkdocs serve -f mkdocs.yml

.PHONY: docs-clean
docs-clean: ## Remove all generated docs
	@echo "+++ $@"
	@rm -rf build/docs-local build/docs-online
	@mkdir -p build/docs-local build/docs-online

.PHONY: clean
clean: docs-clean test-sim-clean build-env-clean  ## Remove all artifacts
	@echo "+++ $@"

.PHONY: test-all-local
test-all-local: clean provision-local build-env docs-online-build test-scripts test-sim ## Run all tests using local build deps
	@echo "+++ $@"

.PHONY: test-all-container
test-all-container: clean provision-container ## Run all tests using container build deps
	@echo "+++ $@"
	@./scripts/provision_shell.sh make test-all-local

.PHONY: try-renovate
try-renovate: ## Run Renovate in dry-run mode
	@echo "+++ $@"
	@echo "Running Renovate dry-run. This may take a while..."
	@$(_CONTAINER_CMD) run --rm -v "$(ROOTDIR):/usr/src/app" -e LOG_LEVEL=info renovate/renovate:latest renovate --dry-run=full
