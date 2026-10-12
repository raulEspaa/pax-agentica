.DEFAULT_GOAL := help
.PHONY: help sync fmt lint types test check precommit-install

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

sync: ## Create .venv and install everything from uv.lock
	uv sync

fmt: ## Format the code and apply safe lint fixes
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint and check formatting (no changes)
	uv run ruff check .
	uv run ruff format --check .

types: ## Type-check with mypy (strict)
	uv run mypy

test: ## Run the tests
	uv run pytest

check: lint types test ## Everything CI runs: lint, types, tests

precommit-install: ## Install the git hooks (ruff, gitleaks) once per clone
	uv run pre-commit install
