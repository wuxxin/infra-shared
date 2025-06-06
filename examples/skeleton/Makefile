# makefile
ROOTDIR := $(dir $(realpath $(firstword $(MAKEFILE_LIST))))
TMPDIR  := $(shell ls -d /var/tmp/build.???? 2>/dev/null || mktemp -d /var/tmp/build.XXXX && chmod 0755 /var/tmp/build.????)/

# Find and return full path to command by name, or throw error if none can be found in PATH.
find-cmd = $(or $(firstword $(wildcard $(addsuffix /$(1),$(subst :, ,$(PATH))))),$(error "Command '$(1)' not found in PATH"))

# default target, calling make without args will show help
.DEFAULT_GOAL := help

# default CONTAINER_CMD, will use podman instead of docker as default
CONTAINER_CMD := podman

# skip annoying version information
PULUMI_SKIP_UPDATE_CHECK=true
PULUMI_DIY_BACKEND_GZIP=true

# add some default arguments to pulumi
PULUMI := pulumi --logtostderr --logflow --non-interactive
PULUMI_INTERACTIVE := pulumi --logtostderr --logflow

# translate json to list of json keys in yaml
define json2keylist_python
import json
import sys
def itd(d,lvl=0,max_lvl=0):
  for k,v in d.items():
    if(isinstance(v,dict)):
      if max_lvl == 0 or lvl < max_lvl:
        print(" "*lvl*2, "-", k)
      itd(v,lvl+1)
      continue
    if max_lvl == 0 or lvl < max_lvl:
      print(" "*lvl*2, "-", k)
itd(json.loads(sys.stdin.read()))
endef
export json2keylist_python
json2keylist := python -c "$$json2keylist_python"

# define a browser open function
define BROWSER_PYSCRIPT
import os, webbrowser, sys
try:
	from urllib import pathname2url
except:
	from urllib.request import pathname2url
webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT
BROWSER := python -c "$$BROWSER_PYSCRIPT"


.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' | sort

.PHONY: submodules
submodules: ## Pull and update git submodules recursively
	@echo "+ $@"
	@git pull --recurse-submodules
	@git submodule update --init --recursive


.PHONY: provision-client
provision-client: ## Build provision client container
	@echo "+ $@"
	@cd infra/Containerfile/provision-client && $(CONTAINER_CMD) build -t provision-client:latest $$(pwd)

.PHONY: install-requirements
install-requirements: ## Install tools used for devop tasks
	@echo "+ $@"
	@./infra/scripts/requirements.sh --install
	@./infra/scripts/requirements.sh --install-aur

uv.lock: pyproject.toml
	@echo "+ $@"
	@./infra/scripts/requirements.sh --check
	@uv lock

.venv/bin/activate: uv.lock
	@echo "+ $@"
	@./infra/scripts/requirements.sh --check
	# create venv
	@if test -d .venv; then rm -rf .venv; fi
	@uv venv
	# sync with locked dependencies from uv.lock
	@uv sync
	# register environment with local ipykernel environment
	@uv run python -m ipykernel install --user --name=$$(basename $(ROOTDIR))

.PHONY: build-env
build-env: .venv/bin/activate ## Build python environment

.PHONY: py-clean
py-clean: ## Remove python related artifacts
	@echo "+ $@"
	@find . -type d -name '__pycache__' -exec rm -rf {} +
	@find . -type d -name '.ipynb_checkpoints' -exec rm -rf {} +
	@find . -type f -name '*.py[co]' -exec rm -f {} +

.PHONY: build-env-clean
build-env-clean: py-clean ## Remove build environment artifacts
	@echo "+ $@"
	@rm -rf .venv


Pulumi.sim.yaml: build-env
ifeq ($(shell test -f Pulumi.sim.yaml && echo "ok"), ok)
	@touch -c Pulumi.sim.yaml
else
	@echo "+ $@"
	@mkdir -p $(ROOTDIR)state/pulumi
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack init sim --secrets-provider passphrase
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack "select" "sim"
	@cat config-template.yaml >> Pulumi.sim.yaml
endif

.PHONY: sim-create
sim-create: Pulumi.sim.yaml ## Create pulumi "sim" stack

.PHONY: sim-up
sim-up: sim-create ## Run "pulumi up --stack=sim $(args)
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) up --stack "sim" --suppress-outputs --yes $(args)

.PHONY: sim-preview
sim-preview: sim-create ## Run "pulumi preview --stack=sim --suppress-outputs $(args)
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) preview --stack "sim" --suppress-outputs $(args)

.PHONY: sim-tool
sim-tool: sim-create ## Run "infra/scripts/resource_call.py --stack sim $(args)"
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="sim" uv run ./infra/scripts/resource_call.py --stack sim $(args)

.PHONY: sim-show
sim-show: ## Run "pulumi stack output --stack=sim --json $(args)"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack output --json --stack "sim" $(args)

.PHONY: sim-list
sim-list: ## Run "pulumi stack output --stack=sim --json | json2keylist"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack output --json --stack "sim" | $(json2keylist)

.PHONY: sim__
sim__: ## Run "pulumi $(args) --stack sim"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@if test "$(args)" = "" -o "$(args)" = "help"; then PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI_INTERACTIVE) help;  else PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI_INTERACTIVE) $(args) --stack "sim"; fi

.PHONY: sim-clean
sim-clean: ## Remove/Destroy "sim" stack
ifeq ($(shell test -f Pulumi.sim.yaml && echo "ok"), ok)
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:index:CACertFactoryVault$$command:local:Command::ca_factory_vault_ca' || true
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:index:CACertFactoryVault$$command:local:Command::fake_ca_factory_vault_ca' || true
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:index:CACertFactoryPulumi$$tls:index/selfSignedCert:SelfSignedCert::ca_factory_root_cert' || true
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:index:CACertFactoryPulumi$$tls:index/privateKey:PrivateKey::ca_factory_root_key' || true
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:index:CACertFactoryPulumi$$tls:index/selfSignedCert:SelfSignedCert::fake_ca_factory_root_cert' || true
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:index:CACertFactoryPulumi$$tls:index/privateKey:PrivateKey::fake_ca_factory_root_key' || true
	@PULUMI_CONFIG_PASSPHRASE="sim" PULUMI_CONTINUE_ON_ERROR=true $(PULUMI) destroy --stack "sim" --yes || true
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack rm "sim" --yes  || true
	@rm -rf state/pulumi/.pulumi/backups/sim state/pulumi/.pulumi/history/sim
	@rm Pulumi.sim.yaml
endif


.PHONY: docs
docs: build-env ## Build docs for local usage and open in browser
	@echo "+ $@"
	@mkdir -p state/docs
	@uv run mkdocs build --no-directory-urls -d state/docs -f mkdocs.yml
	@echo "finished. browse documentation at state/docs/index.html"
	@$(BROWSER) state/docs/index.html

.PHONY: docs-online-build
docs-online-build: build-env ## Build docs for http serve
	@echo "+ $@"
	@mkdir -p state/docs/online
	@uv run mkdocs build -d state/docs/online -f mkdocs.yml

.PHONY: docs-serve
docs-serve: build-env ## Rebuild and serve docs with autoreload
	@echo "+ $@"
	@uv run mkdocs serve -f mkdocs.yml

.PHONY: docs-infra
docs-infra: build-env ## Build infra/docs for local usage and open in browser
	@echo "+ $@"
	@mkdir -p state/docs/infra
	@uv run mkdocs build --no-directory-urls -d ../state/docs/infra -f infra/mkdocs.yml
	@echo "finished. browse documentation at state/docs/infra/index.html"
	@$(BROWSER) state/docs/infra/index.html

.PHONY: docs-clean
docs-clean: ## Remove all generated docs
	@echo "+ $@"
	@rm -rf state/docs
	@mkdir -p state/docs


.PHONY: clean-all
clean-all: sim-clean build-env-clean py-clean docs-clean ## Remove build, docs, tmp, salt & sim stack artifacts
	@echo "+ $@"
	@rm -rf state/tmp
	@rm -rf state/salt
	@mkdir state/tmp state/salt


.PHONY: check_authorized_keys
check_authorized_keys:
	@if test ! -s $(ROOTDIR)authorized_keys; then echo "ERROR: 'authorized_keys' is empty."; exit 1; fi

prod_passphrase.age: build-env check_authorized_keys
ifeq ($(shell test -f prod_passphrase.age && echo "ok"), ok)
	@touch -c prod_passphrase.age
else
	@echo "+ $@"
	@openssl rand --base64 24 | age --encrypt -R $(ROOTDIR)authorized_keys -a > prod_passphrase.age
endif

Pulumi.prod.yaml: build-env check_authorized_keys
ifeq ($(shell test -f Pulumi.prod.yaml && echo "ok"), ok)
	@touch -c Pulumi.prod.yaml
else
	@echo "+ $@"
	@mkdir -p $(ROOTDIR)state/pulumi
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) stack init prod --secrets-provider passphrase
endif

.PHONY: prod-create
prod-create: prod_passphrase.age Pulumi.prod.yaml ## Create pulumi "prod" stack

.PHONY: prod-tool
prod-tool: prod-create ## Run "infra/scripts/resource_call.py --stack prod $(args)"
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" uv run ./infra/scripts/resource_call.py --stack prod $(args)

.PHONY: prod-show
prod-show: ## Run "pulumi stack output --stack "prod" --json $(args)"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) stack output --json --stack "prod" $(args)

.PHONY: prod-up
prod-up: prod-create ## Run "pulumi up --stack=prod $(args)
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) up --stack "prod" --suppress-outputs $(args)

.PHONY: prod-preview
prod-preview: prod-create ## Run "pulumi preview --stack=prod --suppress-outputs $(args)
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) preview --stack "prod" --suppress-outputs $(args)

.PHONY: prod__
prod__: prod-create ## Run pulumi $(args) --stack "prod"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@if test "$(args)" = "" -o "$(args)" = "help"; then $(PULUMI_INTERACTIVE) help; else PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI_INTERACTIVE) $(args) --stack "prod"; fi
