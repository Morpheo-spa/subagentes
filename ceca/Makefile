.DEFAULT_GOAL := help
SHELL := /bin/bash
.ONESHELL:
COMPOSE := docker compose
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
	@$(PY) - <<-'PYCODE'
	import re, secrets, pathlib
	from cryptography.fernet import Fernet
	path = pathlib.Path(".env")
	text = path.read_text(encoding="utf-8")
	fill = lambda body, key, value: re.sub(rf"(?m)^{key}=CHANGE_ME.*$$", f"{key}={value}", body)
	text = fill(text, "JWT_SECRET_KEY", secrets.token_urlsafe(48))
	text = fill(text, "STORAGE_SECRET_KEY", Fernet.generate_key().decode())
	text = fill(text, "ACCESS_LOG_IP_SALT", secrets.token_urlsafe(24))
	text = fill(text, "MINIO_ROOT_PASSWORD", secrets.token_urlsafe(18))
	path.write_text(text, encoding="utf-8")
	print("secrets written to .env")
	PYCODE

.PHONY: up
up: env ## Start the whole stack
	$(COMPOSE) up --build -d

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: logs
logs: ## Follow the API and worker logs
	$(COMPOSE) logs -f api worker

.PHONY: migrate
migrate: ## Apply migrations up to head
	$(COMPOSE) exec api alembic upgrade head

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="message"
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

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
	$(COMPOSE) down -v
