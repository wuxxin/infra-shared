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


.PHONY: submodules
submodules: ## Pull and update git submodules recursively
	@echo "+ $@"
	git pull --recurse-submodules
	git submodule update --init --recursive

.PHONY: provision-client
provision-client: ## Build dependencies for provisioning using a container
	@echo "+ $@"
	$(_CONTAINER_CMD) build -t provision-client:latest -f infra/Containerfile/provision-client/Containerfile infra/Containerfile/provision-client

.PHONY: install-requirements
install-requirements: ## Build dependencies for provisioning using system apps
	@echo "+ $@"
	./infra/scripts/requirements.sh --install
	./infra/scripts/requirements.sh --install-extra

uv.lock: pyproject.toml
	@echo "+ $@"
	./infra/scripts/requirements.sh --check
	uv lock

.venv/bin/activate: uv.lock
	@echo "+ $@"
	@./infra/scripts/requirements.sh --check
	# create venv
	if test -d .venv; then rm -rf .venv; fi
	uv venv
	# sync with locked dependencies including extras from uv.lock
	uv sync --all-extras
	# register environment with local ipykernel environment
	. .venv/bin/activate && python -m ipykernel install --user --name=$$(basename $(ROOTDIR)/)

.PHONY: buildenv
buildenv: .venv/bin/activate ## Build python environment

.PHONY: py-clean
py-clean: ## Remove python related artifacts
	@echo "+ $@"
	find . -type d -name '__pycache__' -exec rm -rf {} +
	find . -type d -name '.ipynb_checkpoints' -exec rm -rf {} +
	find . -type f -name '*.py[co]' -exec rm -f {} +

.PHONY: buildenv-clean
buildenv-clean: py-clean ## Remove build environment artifacts
	@echo "+ $@"
	rm -rf .venv


Pulumi.sim.yaml: buildenv
ifeq ($(shell test -f Pulumi.sim.yaml && echo "ok"), ok)
	@touch -c Pulumi.sim.yaml
else
	@echo "+ $@"
	mkdir -p $(ROOTDIR)/state/pulumi
	$(PULUMI) login file://$(ROOTDIR)/state/pulumi
	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack init sim --secrets-provider passphrase
	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack "select" "sim"
	cat config-template.yaml >> Pulumi.sim.yaml
endif

.PHONY: sim-create
sim-create: Pulumi.sim.yaml ## Create pulumi "sim" stack

.PHONY: sim-up
sim-up: sim-create ## Run "pulumi up --stack=sim $(args)
	@echo "+ $@"
	$(PULUMI) login file://$(ROOTDIR)/state/pulumi
	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) up --stack "sim" --suppress-outputs --yes $(args)

.PHONY: sim-preview
sim-preview: sim-create ## Run "pulumi preview --stack=sim --suppress-outputs $(args)
	@echo "+ $@"
	$(PULUMI) login file://$(ROOTDIR)/state/pulumi
	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) preview --stack "sim" --suppress-outputs $(args)

.PHONY: sim-show
sim-show: ## Run "pulumi stack output --stack=sim --json $(args)"
	@$(PULUMI) login file://$(ROOTDIR)/state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack output --json --stack "sim" $(args)

.PHONY: sim-list
sim-list: ## Run "pulumi stack output --stack=sim --json | json2keylist"
	@$(PULUMI) login file://$(ROOTDIR)/state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack output --json --stack "sim" | $(json2keylist)

.PHONY: sim__
sim__: ## Run "pulumi $(args)" on sim stack
	@$(PULUMI) login file://$(ROOTDIR)/state/pulumi &> /dev/null
	@$(PULUMI) stack select sim &> /dev/null
	@if test "$(args)" = "" -o "$(args)" = "help"; then PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI_INTERACTIVE) help; else PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI_INTERACTIVE) $(args); fi

.PHONY: sim-clean
sim-clean: ## Remove/Destroy "sim" stack
ifeq ($(shell test -f Pulumi.sim.yaml && echo "ok"), ok)
	@echo "+ $@"
	$(PULUMI) login file://$(ROOTDIR)/state/pulumi
	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:authority:CACertFactoryVault$$command:local:Command::ca_factory_vault_ca' || true
	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:authority:CACertFactoryPulumi$$tls:index/selfSignedCert:SelfSignedCert::ca_factory_root_cert' || true
	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) --stack "sim" state unprotect --yes 'urn:pulumi:sim::athome::pkg:authority:CACertFactoryPulumi$$tls:index/privateKey:PrivateKey::ca_factory_root_key' || true
	PULUMI_CONFIG_PASSPHRASE="sim" PULUMI_CONTINUE_ON_ERROR=true $(PULUMI) destroy --stack "sim" --yes || true
	PULUMI_CONFIG_PASSPHRASE="sim" $(PULUMI) stack rm "sim" --yes  || true
	rm -rf state/pulumi/.pulumi/backups/sim state/pulumi/.pulumi/history/sim
	rm Pulumi.sim.yaml
endif


.PHONY: docs
docs: buildenv ## Build docs for local usage
	@echo "+ $@"
	mkdir -p build/docs
	. .venv/bin/activate && mkdocs build --no-directory-urls -d build/docs -f mkdocs.yml
	@echo "Finished. Browse at file:///$(ROOTDIR)/build/docs/index.html"

.PHONY: docs-online-build
docs-online-build: buildenv ## Build docs for http serve
	@echo "+ $@"
	mkdir -p build/docs-online
	. .venv/bin/activate && mkdocs build -d build/docs-online -f mkdocs.yml
	@echo "Finished. serve with"
	@echo ". .venv/bin/activate && python -m http.server --directory build/docs-online"

.PHONY: docs-serve
docs-serve: buildenv ## Rebuild and serve docs with autoreload
	@echo "+ $@"
	. .venv/bin/activate && mkdocs serve -f mkdocs.yml

.PHONY: docs-clean
docs-clean: ## Remove all generated docs
	@echo "+ $@"
	rm -rf build/docs build/docs-online
	mkdir -p build/docs build/docs-online


.PHONY: clean-all
clean-all: sim-clean buildenv-clean py-clean docs-clean ## Remove build, docs, tmp, salt & sim stack artifacts
	@echo "+ $@"
	rm -rf build/tmp
	rm -rf build/salt
	mkdir build/tmp build/salt


.PHONY: check_authorized_keys
check_authorized_keys:
	@if test ! -s $(ROOTDIR)/authorized_keys; then echo "ERROR: 'authorized_keys' is empty."; exit 1; fi

prod_passphrase.age: buildenv check_authorized_keys
ifeq ($(shell test -f prod_passphrase.age && echo "ok"), ok)
	@touch -c prod_passphrase.age
else
	@echo "+ $@"
	@openssl rand --base64 24 | age --encrypt -R $(ROOTDIR)/authorized_keys -a > prod_passphrase.age
endif

Pulumi.prod.yaml: buildenv check_authorized_keys
ifeq ($(shell test -f Pulumi.prod.yaml && echo "ok"), ok)
	@touch -c Pulumi.prod.yaml
else
	@echo "+ $@"
	@mkdir -p $(ROOTDIR)/state/pulumi
	@$(PULUMI) login file://$(ROOTDIR)/state/pulumi
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) stack init prod --secrets-provider passphrase
endif

.PHONY: prod-create
prod-create: prod_passphrase.age Pulumi.prod.yaml ## Create pulumi "prod" stack

.PHONY: prod-show
prod-show: ## Run "pulumi stack output --stack "prod" --json $(args)"
	@$(PULUMI) login file://$(ROOTDIR)/state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) stack output --json --stack "prod" $(args)

.PHONY: prod-up
prod-up: prod-create ## Run "pulumi up --stack=prod $(args)
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)/state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) up --stack "prod" --suppress-outputs $(args)

.PHONY: prod-preview
prod-preview: prod-create ## Run "pulumi preview --stack=prod --suppress-outputs $(args)
	@echo "+ $@"
	@$(PULUMI) login file://$(ROOTDIR)/state/pulumi &> /dev/null
	@PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI) preview --stack "prod" --suppress-outputs $(args)

.PHONY: prod__
prod__: prod-create ## Run pulumi "$(args)" on prod stack
	@$(PULUMI) login file://$(ROOTDIR)/state/pulumi &> /dev/null
	@$(PULUMI) stack select prod
	@if test "$(args)" = "" -o "$(args)" = "help"; then $(PULUMI_INTERACTIVE) help; else PULUMI_CONFIG_PASSPHRASE="$$(age --decrypt -i ~/.ssh/id_rsa prod_passphrase.age)" $(PULUMI_INTERACTIVE) $(args); fi
