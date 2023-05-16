# makefile
ROOTDIR := $(dir $(realpath $(firstword $(MAKEFILE_LIST))))
TMPDIR  := $(shell ls -d /var/tmp/build.???? 2>/dev/null || mktemp -d /var/tmp/build.XXXX && chmod 0755 /var/tmp/build.????)/

# Find and return full path to command by name, or throw error if none can be found in PATH.
find-cmd = $(or $(firstword $(wildcard $(addsuffix /$(1),$(subst :, ,$(PATH))))),$(error "Command '$(1)' not found in PATH"))

# build-time dependency
PIPENV ?= $(call find-cmd,pipenv)

# set default target
.DEFAULT_GOAL := help

DOCKER := podman

# skip annoying version information
PULUMI_SKIP_UPDATE_CHECK=1
export PULUMI_SKIP_UPDATE_CHECK

# add some default arguments to pulumi
PULUMI := pulumi --logtostderr --logflow 

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


.PHONY: container
container: ## Build infrastructure container
	@echo "+ $@"
	@cd infra/build && sudo -E $(DOCKER) build $$(pwd) -t infra_build:latest

.PHONY: install-requirements
install-requirements: ## Install tools used for devop tasks (uses sudo for install)
	@echo "+ $@"
	@sudo -E $$(pwd)/infra/requirements.sh --install
	@sudo -E $$(pwd)/infra/requirements.sh --install-aur

Pipfile.lock: Pipfile
	@echo "+ $@"
	@$(PIPENV) lock

state/venv: Pipfile.lock
	@echo "+ $@"
	@./infra/requirements.sh --check
	@$(PIPENV) sync
	# register environment with local ipykernel environment
	@$(PIPENV) run python -m ipykernel install --user --name=$$(basename $(ROOTDIR))
	# symlink created virtualenv to state/venv
	@ln -s $$($(PIPENV) --venv -q) ./state/venv

.PHONY: build-env
build-env: state/venv ## Build python environment

.PHONY: python-clean
python-clean: ## Remove python related artifacts
	@echo "+ $@"
	@find . -type d -name '__pycache__' -exec rm -rf {} +
	@find . -type d -name '.ipynb_checkpoints' -exec rm -rf {} +
	@find . -type f -name '*.py[co]' -exec rm -f {} +

.PHONY: build-env-clean
build-env-clean: python-clean ## Remove build environment artifacts
	@echo "+ $@"
	@if readlink -e state/venv; then rm -rf $$(readlink -e state/venv); fi
	@rm -f state/venv


prod_passphrase.age: build-env
ifeq ($(shell test -f prod_passphrase.age && echo "ok"), ok)
	@touch -c prod_passphrase.age
else
	@echo "+ $@"
	@openssl rand --base64 24 | age --encrypt -R $(ROOTDIR)authorized_keys -a > prod_passphrase.age
endif

Pulumi.prod.yaml: build-env
ifeq ($(shell test -f Pulumi.prod.yaml && echo "ok"), ok)
	@touch -c Pulumi.prod.yaml
else
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) stack init prod --secrets-provider passphrase
endif

.PHONY: prod-create
prod-create: prod_passphrase.age Pulumi.prod.yaml ## Create pulumi "prod" stack

.PHONY: prod__
prod__: prod-create ## Run pulumi --stack "prod" $(args)
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) --stack prod $(args)


Pulumi.sim.yaml: build-env
ifeq ($(shell test -f Pulumi.sim.yaml && echo "ok"), ok)
	@touch -c Pulumi.sim.yaml
else
	@echo "+ $@"
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
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) up --stack "sim" --yes $(args)

.PHONY: sim-show
sim-show: ## Run "pulumi stack output --stack=sim --json $(args)"
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack output --json --stack "sim" $(args)

.PHONY: sim__
sim__: ## Run "pulumi --stack sim $(args)", eg. 'make sim__ "args=config"'
	@$(PULUMI) login file://$(ROOTDIR)state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" $(args)

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
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) destroy --stack "sim" --yes
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack rm "sim" --yes
	@rm -rf state/pulumi/.pulumi/backups/sim state/pulumi/.pulumi/history/sim
endif


.PHONY: docs
docs: build-env ## Build mkdocs documentation
	@echo "+ $@"
	@pipenv run mkdocs build -f mkdocs.yml
	@echo "finished. browse documentation at state/site/index.html"
	@$(BROWSER) state/site/index.html

.PHONY: docs-serve
docs-serve: build-env ## Rebuild and serve docs with autoreload
	@echo "+ $@"
	@pipenv run mkdocs serve -f mkdocs.yml

.PHONY: docs-clean
docs-clean: ## Remove local docs
	@echo "+ $@"
	@rm -rf state/site
	@mkdir state/site


.PHONY: clean-all
clean-all: sim-clean build-env-clean python-clean docs-clean ## Remove build, docs, tmp, salt & sim stack artifacts
	@echo "+ $@"
	@rm -rf state/tmp
	@rm -rf state/salt
	@mkdir state/tmp state/salt

.PHONY: submodules
submodules: ## Pull and update git submodules recursively
	@echo "+ $@"
	@git pull --recurse-submodules
	@git submodule update --init --recursive

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' | sort
