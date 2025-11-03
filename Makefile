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
	uv sync --all-extras

.PHONY: buildenv
buildenv: .venv/bin/activate ## Build python environment

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
pytest: buildenv ## Run pytest Tests
	@echo "+++ $@"
	mkdir -p build/tests/
	. .venv/bin/activate && pytest tests/

.PHONY: pytest-clean
pytest-clean: ## Remove pytest Artifacts
	@echo "+++ $@"
	if test -d $(ROOTDIR)/build/tests; then rm -rf $(ROOTDIR)/build/tests; fi

.PHONY: test-scripts
test-scripts: buildenv ## Run script Tests
	@echo "+++ $@"
	. .venv/bin/activate && scripts/test_serve_once.py

.PHONY: test-sim
test-sim: buildenv ## Run sim up Tests
	@echo "+++ $@"
	mkdir -p $(ROOTDIR)/build/test_sim
	git init $(ROOTDIR)/build/test_sim
	./scripts/create_skeleton.sh \
		--project-dir $(ROOTDIR)/build/test_sim --name-library infra --yes
	mkdir -p $(ROOTDIR)/build/test_sim/state/pulumi $(ROOTDIR)/build/test_sim/target
	for i in infra uv.lock .venv; do \
	    f=$(ROOTDIR)/build/test_sim/$$i && if test ! -e $$f; then ln -s "../../" $$f; fi \
	done
	sed -i -r "s#virtualenv: .venv#virtualenv: ../../.venv#g" $(ROOTDIR)/build/test_sim/Pulumi.yaml
	cp -r $(ROOTDIR)/examples/safe $(ROOTDIR)/build/test_sim/target
	cat $(ROOTDIR)/build/test_sim/config-template.yaml >> $(ROOTDIR)/build/test_sim/Pulumi.sim.yaml
	printf "  test_sim:safe_showcase_unittest: true\n\n" >> $(ROOTDIR)/build/test_sim/Pulumi.sim.yaml
	echo "import target.safe" >> $(ROOTDIR)/build/test_sim/__main__.py

	cd $(ROOTDIR)/build/test_sim && $(PULUMI) login file://$(ROOTDIR)/build/test_sim/state/pulumi
	cd $(ROOTDIR)/build/test_sim && \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack init sim --secrets-provider passphrase
	cd $(ROOTDIR)/build/test_sim && \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack "select" "sim"
	cd $(ROOTDIR)/build/test_sim && \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) up --stack "sim" --suppress-outputs --yes
	cd $(ROOTDIR)/build/test_sim && \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack output --json --stack "sim" --show-secrets safe_butane | jq -r .this_env

.PHONY: sim__
sim__: ## Run "pulumi $(args)"
	@echo "+++ $@"
	cd $(ROOTDIR)/build/test_sim &&	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI_INTERACTIVE) $(args)

.PHONY: test-sim-clean
test-sim-clean: ## Remove Application Artifacts
	@echo "+++ $@"
	if test -d $(ROOTDIR)/build/test_sim; then \
	    cd $(ROOTDIR)/build/test_sim && \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:authority:CACertFactoryVault$$command:local:Command::ca_factory_vault_ca' || true; \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:authority:CACertFactoryVault$$command:local:Command::fake_ca_factory_vault_ca' || true; \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:authority:CACertFactoryPulumi$$tls:index/selfSignedCert:SelfSignedCert::ca_factory_root_cert' || true; \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:authority:CACertFactoryPulumi$$tls:index/privateKey:PrivateKey::ca_factory_root_key' || true; \
	fi
	if test -d $(ROOTDIR)/build/test_sim; then \
		cd $(ROOTDIR)/build/test_sim && \
		PULUMI_CONFIG_PASSPHRASE="sim" PULUMI_CONTINUE_ON_ERROR=true \
			$(PULUMI) destroy --stack "sim" --yes || true; \
	fi
	if test -d $(ROOTDIR)/build/test_sim; then \
		cd $(ROOTDIR)/build/test_sim && \
		PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack rm "sim" --force --yes  || true; \
	fi
	rm -rf $(ROOTDIR)/build/test_sim $(ROOTDIR)/build/pulumi || true

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
	. .venv/bin/activate && mkdocs build -d build/docs-online -f mkdocs.yml -v
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
clean: pytest-clean test-sim-clean docs-clean buildenv-clean  ## Remove all artifacts
	@echo "+++ $@"
	rm -rf build

.PHONY: test-all-local
test-all-local: clean provision-local buildenv docs-online-build test-scripts test-sim pytest ## Run all tests using local build deps
	@echo "+++ $@"

.PHONY: test-all-container
test-all-container: clean provision-container ## Run all tests using container build deps
	@echo "+++ $@"
	./scripts/provision_shell.sh make test-all-local

.PHONY: try-renovate
try-renovate: ## Run Renovate in dry-run mode
	@echo "+++ $@"
	@echo "Running Renovate dry-run. This may take a while..."
	mkdir -p build/test
	echo 'module.exports = {  "onboarding": false,  "requireConfig": "ignored" };' > build/test/config.js
	$(_CONTAINER_CMD) run --rm \
		-v "$(ROOTDIR):/usr/src/app" -v "$(ROOTDIR)/build/test/config.js:/usr/src/app/config.js" \
		-e GITHUB_COM_TOKEN -e LOG_LEVEL=debug \
		renovate/renovate:latest \
		renovate $(args)"

