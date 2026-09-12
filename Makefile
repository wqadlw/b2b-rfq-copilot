# b2b-rfq-copilot · engineering entry (works in Git Bash on Windows; `make` optional —
# every target is a thin wrapper over a plain command you can run directly).

.DEFAULT_GOAL := help
PY := uv run
FRONTEND_DIR := frontend

.PHONY: help bootstrap dev lint typecheck test policy build frontend-install frontend-build eval

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Install toolchain deps (backend via uv, frontend via pnpm)
	uv sync --extra dev
	cd $(FRONTEND_DIR) && pnpm install

dev: ## Run backend (8000) — frontend dev: `make frontend-dev` or cd frontend && pnpm dev
	$(PY) uvicorn rfq_copilot.app.main:app --reload --port 8000

frontend-dev: ## Run frontend dev server (5173)
	cd $(FRONTEND_DIR) && pnpm dev

lint: ## Backend lint (ruff) + frontend lint (eslint)
	$(PY) ruff check .
	cd $(FRONTEND_DIR) && pnpm lint

typecheck: ## Backend mypy strict + frontend tsc
	$(PY) mypy
	cd $(FRONTEND_DIR) && pnpm exec tsc --noEmit

test: ## Backend pytest
	$(PY) pytest -q

build: ## Frontend production build
	cd $(FRONTEND_DIR) && pnpm build

policy: ## Repo policy scan (secrets / private-site markers)
	$(PY) python scripts/check_repo_policy.py

eval: ## Run evaluation baseline (seed cases + B derivation)
	$(PY) python scripts/run_eval.py

frontend-install: ## Install frontend deps only
	cd $(FRONTEND_DIR) && pnpm install

frontend-build: ## Build frontend only
	cd $(FRONTEND_DIR) && pnpm build
