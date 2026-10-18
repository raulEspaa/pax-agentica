.DEFAULT_GOAL := help
.PHONY: help sync fmt lint types test check precommit-install map host image deploy-tables

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

NE := .cache/naturalearth
NE_URL := https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson

map: ## Rebuild the map asset from Natural Earth (downloads ~48 MB the first time)
	mkdir -p $(NE)
	for f in ne_10m_admin_1_states_provinces_lakes ne_10m_rivers_lake_centerlines; do \
		test -f $(NE)/$$f.geojson || curl -sSfL -o $(NE)/$$f.geojson $(NE_URL)/$$f.geojson; done
	uv run --group mapgen python scripts/build_map.py \
		$(NE)/ne_10m_admin_1_states_provinces_lakes.geojson $(NE)/ne_10m_rivers_lake_centerlines.geojson

chart: ## Rebuild the chart of the New World from the Natural Earth input of `make map`
	uv run --group mapgen python scripts/build_chart.py \
		$(NE)/ne_10m_admin_1_states_provinces_lakes.geojson

host: ## Host multiplayer tables on your network (http://<this machine>:8000)
	uv run pax host --host 0.0.0.0 --port 8000

image: ## Build the multiplayer tables image (pax-tables:dev) and run it on :8080
	docker build -t pax-tables:dev .
	docker run --rm -p 8080:8080 -v pax-tables:/data pax-tables:dev

deploy-tables: ## Deploy the tables by hand (pushes to main deploy by themselves)
	scripts/deploy_tables.sh
