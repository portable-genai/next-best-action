# D5 Next-Best-Action: Recommendations and Cross-Sell — developer tasks.
#
# The gate (lint + format + types + tests + eval) runs on the local profile with the
# [dev] extra only (no google-cloud-*), matching CI. Override PROFILE=gcp for the managed
# stack, or PROFILE=onprem for the fail-fast migration target.

PY ?= python3.14
VENV ?= .venv
BIN := $(VENV)/bin
PROFILE ?= local

API_APP := next_best_action.api.app:app
API_HOST ?= 127.0.0.1  # no-auth local dev binds loopback; override deliberately
API_PORT ?= 8104
UI_DIR := ui
DEMO_PORT ?= 8110
TF_DIR := infra/terraform

export MKT_NBA_PROFILE := $(PROFILE)

# The demo scripts the gate lints. The renderer, the server and the self-test are in this
# list because the served self-test and the browser walkthrough both read the evidence hooks
# the renderer emits and both start the server, so they are gate-relevant code, not scratch
# scripts.
DEMO_SCRIPTS := scripts/render_recommendation_ui.py scripts/demo_server.py scripts/demo_selftest.py

.PHONY: venv install install-demo install-gcp lock lint format typecheck test eval gate \
        ui-install ui-check portability \
        demo demo-server demo-selftest demo-browser smoke-local run-api run-ui \
        tf-validate tf-plan clean

venv:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip

install: venv ## Install the package + dev tooling (NO GCP SDK — local/onprem profile).
	$(BIN)/python -m pip install -e ".[dev]"

install-demo: venv ## Install the pinned headless-browser extra, then fetch its browser binary.
	$(BIN)/python -m pip install -e ".[dev,demo]"
	$(BIN)/python -m playwright install chromium

install-gcp: ## Install with the managed-stack extra (google-genai, discoveryengine, ...).
	$(BIN)/python -m pip install -e ".[gcp,dev]"

lock: ## Recompile reproducible locks and restore the tag-to-commit evidence header.
	$(BIN)/python scripts/lock.py

lint:
	$(BIN)/ruff check src tests $(DEMO_SCRIPTS)

format:
	$(BIN)/ruff format --check src tests $(DEMO_SCRIPTS)

typecheck:
	$(BIN)/mypy src

test:
	$(BIN)/pytest -m "not integration" -q

eval:
	$(BIN)/python eval/run_eval.py

# The full gate, green before any change lands.
portability:
	PYTHONPATH=src $(BIN)/python scripts/portability_demo.py

gate: lint format typecheck test eval demo-selftest portability

ui-install: ## Install the console's locked dependencies (proves package-lock.json is still valid).
	npm ci --prefix $(UI_DIR)

ui-check: ## The console's gate. assert-hydratable runs LAST, against the artefact just built.
	npm --prefix $(UI_DIR) run lint
	npm --prefix $(UI_DIR) test
	NEXT_TELEMETRY_DISABLED=1 npm --prefix $(UI_DIR) run build
	npm --prefix $(UI_DIR) run assert-hydratable

demo: ## Offline demo: run the recommend flow + render the static audit-first HTML (scripts/out).
	MKT_NBA_PROFILE=local PYTHONPATH=src $(BIN)/python scripts/demo.py
	for f in scripts/out/*.json; do PYTHONPATH=src $(BIN)/python scripts/render_recommendation_ui.py "$$f"; done

demo-server: ## Live, presenter-controlled offline demo server on :$(DEMO_PORT).
	MKT_NBA_PROFILE=local PYTHONPATH=src $(BIN)/python scripts/demo_server.py --render --port $(DEMO_PORT)

demo-selftest:
	MKT_NBA_PROFILE=local PYTHONPATH=src $(BIN)/python scripts/demo_selftest.py

demo-browser: ## Drive the SERVED presenter demo through a real headless browser ([demo] extra).
	MKT_NBA_PROFILE=local $(BIN)/pytest tests/browser -q -rs

smoke-local: ## End-to-end offline smoke: produce a cited recommendation under the local profile.
	MKT_NBA_PROFILE=local $(BIN)/mkt-nba recommend cust-sg-bank-1 -m SG -v banking

run-api: ## Run the real FastAPI service on :$(API_PORT) (PROFILE=$(PROFILE)).
	$(BIN)/uvicorn $(API_APP) --host $(API_HOST) --port $(API_PORT)

run-ui: ## Run the thin Next.js console (dev server); set NEXT_PUBLIC_API_BASE to the API.
	cd $(UI_DIR) && npm install && npm run dev

tf-plan: ## Terraform plan for the pinned Singapore region (residency posture check).
	cd $(TF_DIR) && terraform init -backend=false && terraform plan

tf-validate:
	cd $(TF_DIR) && terraform fmt -check -recursive && terraform init -backend=false -input=false && terraform validate

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
