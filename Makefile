# Package directory
PKG_DIR := ./mcp_sentinel
TESTS_DIR := ./tests

##@ Development

.PHONY: install install-dev run clean fmt lint lint-fix type-check check-lint

install: ## Install the package
	uv pip install -e .

install-dev: ## Install the package with development dependencies
	uv sync --dev

run: ## Run the application
	uv run python -m mcp_sentinel --config config.yaml run

fmt: ## Format Python code with ruff
	uv run ruff format $(PKG_DIR) $(TESTS_DIR)

lint: ## Run linting with ruff
	uv run ruff check $(PKG_DIR) $(TESTS_DIR)

lint-fix: ## Run linting with ruff and auto-fix issues
	uv run ruff check --fix $(PKG_DIR) $(TESTS_DIR)

type-check: ## Run type checking with mypy
	uv run mypy $(PKG_DIR)

check-lint: lint type-check ## Run all linting and type checking

##@ Testing

.PHONY: test test-coverage test-unit test-integration

test: ## Run all tests
	uv run pytest $(TESTS_DIR)

test-coverage: ## Run tests with coverage report
	uv run pytest --cov=$(PKG_DIR) --cov-report=html --cov-report=term $(TESTS_DIR)

test-unit: ## Run unit tests only
	uv run pytest $(TESTS_DIR) -k "not integration"

test-integration: ## Run integration tests only
	uv run pytest $(TESTS_DIR) -k "integration"

##@ Help

.PHONY: help

help:  ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
