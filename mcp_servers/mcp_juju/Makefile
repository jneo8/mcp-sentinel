# Package directory
PKG_DIR := ./mcp_juju

##@ Development

.PHONY: install install-dev run clean fmt lint lint-fix

install: ## Install the package
	uv pip install -e .

install-dev: ## Install the package with development dependencies
	uv sync --dev

run: ## Run the MCP server
	uv run mcp-juju

fmt: ## Format Python code with ruff
	uv run ruff format $(PKG_DIR)

lint: ## Run linting with ruff
	uv run ruff check $(PKG_DIR)

lint-fix: ## Run linting with ruff and auto-fix issues
	uv run ruff check --fix $(PKG_DIR)

clean: ## Clean build artifacts
	rm -rf build dist *.egg-info .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

##@ Testing

.PHONY: test

test: ## Run tests
	uv run pytest

##@ Help

.PHONY: help

help:  ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
