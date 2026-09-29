# One entry point for local and CI runs: the CI verify job calls `make verify`. Offline: no AWS credentials and no
# AWS API calls. The first run downloads Python packages, the Terraform provider, the tflint AWS ruleset, Semgrep
# rules and the Trivy checks bundle.
.DEFAULT_GOAL := help
SHELL := bash
.SHELLFLAGS := -euo pipefail -c

UV ?= uv
RUN := $(UV) run --locked
PY := PYTHONPATH=scripts $(RUN) python -m genai_review
CHECKOV_VERSION := 3.3.19
SEMGREP_VERSION := 1.178.0
TF_DIR := fixes/terraform
TFLINT_CONFIG := $(CURDIR)/.tflint.hcl
# Same image and arguments as the shared report workflow in gamaware/.github, so CI and the committed PDF match.
PANDOC_IMAGE := pandoc/latex:3.11@sha256:cdbf139f607237498b412b3aa051008311d69b88006ab47550efba357af3b277
PANDOC_ARGS := --pdf-engine=xelatex -V geometry:margin=2.2cm --toc

.PHONY: help setup lint test check tf-verify checkov trivy semgrep verify evidence pdf clean

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## Install the pinned Python toolchain into .venv
	$(UV) sync --locked

lint: ## Ruff lint and format check (scripts, tests, application fixes)
	$(RUN) ruff check scripts tests fixes/app
	$(RUN) ruff format --check scripts tests fixes/app

test: ## Check, cost model, report and application-fix tests
	$(RUN) pytest

check: ## Fail if evidence/ or the generated report blocks differ from what data/ produces
	$(PY) check

tf-verify: ## fmt check, validate, tflint and mocked terraform test of the Terraform fixes
	terraform fmt -check -recursive $(TF_DIR)
	terraform -chdir=$(TF_DIR) init -backend=false -input=false > /dev/null
	terraform -chdir=$(TF_DIR) validate
	cd $(TF_DIR) && tflint --init --config=$(TFLINT_CONFIG) > /dev/null && tflint --config=$(TFLINT_CONFIG)
	terraform -chdir=$(TF_DIR) test

checkov: ## Policy checks on the Terraform fixes and the workflows (.checkov.yaml)
	$(UV) tool run checkov==$(CHECKOV_VERSION) --config-file .checkov.yaml

trivy: ## Misconfiguration scan of the repository, including the as-found plan
	trivy config --quiet --exit-code 1 --severity HIGH,CRITICAL --skip-dirs '**/.terraform' .

semgrep: ## Semgrep Python and Terraform rules
	$(UV) tool run semgrep==$(SEMGREP_VERSION) scan --config p/python --config p/terraform --metrics=off --error --quiet \
		scripts tests fixes

verify: lint test check tf-verify checkov trivy semgrep ## Every offline check (CI runs these plus the shared checks)
	@echo "verify: all checks passed"

evidence: ## Regenerate evidence/ and the generated blocks in report/REPORT.md and README.md
	$(PY) generate

pdf: ## Render report/REPORT.pdf from report/REPORT.md (pandoc + LaTeX in Docker)
	docker run --rm --platform linux/amd64 --user "$$(id -u):$$(id -g)" -e HOME=/tmp \
		-v "$(CURDIR):/data" -w /data/report $(PANDOC_IMAGE) REPORT.md $(PANDOC_ARGS) -o REPORT.pdf

clean: ## Remove caches and local Terraform state
	rm -rf .pytest_cache .ruff_cache $(TF_DIR)/.terraform
