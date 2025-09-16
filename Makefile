.PHONY: clean lint format typecheck test install dev-install

# Clean and fix all code quality issues
clean: format lint typecheck
	@echo "✅ Code quality checks complete"

# Format code with black
format:
	@echo "🎨 Formatting code with black..."
	black mcp_sfd/ tests/

# Run linter with auto-fix
lint:
	@echo "🔍 Running ruff linter with auto-fix..."
	ruff check --fix mcp_sfd/ tests/

# Run type checker in strict mode
typecheck:
	@echo "🔬 Running mypy type checker..."
	mypy mcp_sfd/

# Run tests
test:
	@echo "🧪 Running tests..."
	pytest

# Run tests with coverage
test-cov:
	@echo "🧪 Running tests with coverage..."
	pytest --cov=mcp_sfd --cov-report=term-missing

# Install package in development mode
dev-install:
	@echo "📦 Installing package in development mode..."
	pip install -e ".[dev]"

# Install just the package
install:
	@echo "📦 Installing package..."
	pip install -e .

# Run the MCP server
run:
	@echo "🚀 Starting MCP server..."
	python -m mcp_sfd.server

# Full development cycle: install, clean, test
dev: dev-install clean test
	@echo "🎉 Development cycle complete"

# Help target
help:
	@echo "Available targets:"
	@echo "  clean      - Format, lint, and typecheck code"
	@echo "  format     - Format code with black"
	@echo "  lint       - Run ruff linter with auto-fix"
	@echo "  typecheck  - Run mypy type checker"
	@echo "  test       - Run tests"
	@echo "  test-cov   - Run tests with coverage"
	@echo "  install    - Install package"
	@echo "  dev-install - Install package in development mode"
	@echo "  run        - Start MCP server"
	@echo "  dev        - Full development cycle"
	@echo "  help       - Show this help"