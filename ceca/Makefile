.DEFAULT_GOAL := help
SHELL := /bin/bash
.ONESHELL:
COMPOSE := docker compose
# Development runs the base stack plus the dev overlay, which has to be named
# explicitly: it is no longer called docker-compose.override.yml, so a bare
# `docker compose up` on a server brings up the hardened stack (audit E-15).
COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml
# Prefer the backend virtualenv when it exists, like scripts/ci.sh does.
PY := $(shell [ -x backend/.venv/bin/python ] && echo backend/.venv/bin/python || echo python3)

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: env
env: ## Create .env from the template if it does not exist
	@test -f .env || cp .env.example .env
	@echo ".env ready. Run 'make secrets' to fill in the generated secrets."

.PHONY: secrets
secrets: env ## Replace the CHANGE_ME placeholders in .env with fresh secrets
	@$(PY) scripts/make_secrets.py .env

.PHONY: garage-init
garage-init: ## Apply the single-node layout, bucket and access key to the running Garage
	$(PY) scripts/garage_init.py

.PHONY: up
up: env ## Start the development stack (base + dev overlay)
	$(COMPOSE_DEV) up --build -d

.PHONY: up-prod
up-prod: ## Start the hardened stack only, after validating .env
	$(PY) scripts/check_env.py .env
	$(COMPOSE) up --build -d

.PHONY: down
down: ## Stop the stack
	$(COMPOSE_DEV) down

.PHONY: logs
logs: ## Follow the API and worker logs
	$(COMPOSE_DEV) logs -f api worker

.PHONY: migrate
migrate: ## Apply migrations up to head
	$(COMPOSE_DEV) exec api alembic upgrade head

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="message"
	$(COMPOSE_DEV) exec api alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Load the demo tenant
	$(PY) scripts/seed_demo.py

.PHONY: test
test: ## Run the backend test suite
	cd backend && pytest -v

.PHONY: lint
lint: ## Lint and type-check the backend
	cd backend && ruff check . && ruff format --check . && mypy app

.PHONY: ci
ci: ## Run the full local gate, the same one CI runs
	bash scripts/ci.sh

.PHONY: check-env
check-env: ## Validate a production env file: make check-env f=.env.production
	$(PY) scripts/check_env.py $(f)

.PHONY: clean
clean: ## Remove containers and volumes
	$(COMPOSE_DEV) down -v
