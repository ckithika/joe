# Contributing to Joe AI

Thank you for your interest in contributing to Joe AI! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Development Setup](#development-setup)
- [Code Style](#code-style)
- [Pull Request Process](#pull-request-process)
- [Commit Message Convention](#commit-message-convention)

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## Reporting Bugs

Before reporting a bug, please check the [existing issues](https://github.com/charleskithika/ai-trading-agent/issues) to avoid duplicates.

When filing a bug report, please use the [Bug Report issue template](https://github.com/charleskithika/ai-trading-agent/issues/new?template=bug_report.md) and include:

- A clear, descriptive title
- Steps to reproduce the behavior
- Expected vs. actual behavior
- Your environment (Python version, OS, broker connection type)
- Relevant logs or error messages
- Configuration details (with sensitive values redacted)

**Important:** Never include API keys, passwords, or account credentials in bug reports.

## Suggesting Features

Feature requests are welcome! Please use the [Feature Request issue template](https://github.com/charleskithika/ai-trading-agent/issues/new?template=feature_request.md) and include:

- A clear description of the problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered
- Whether you'd be willing to implement the feature

## Development Setup

1. **Fork and clone the repository:**

   ```bash
   git clone https://github.com/YOUR_USERNAME/ai-trading-agent.git
   cd ai-trading-agent
   ```

2. **Create a virtual environment:**

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**

   ```bash
   make install-dev
   ```

   Or manually:

   ```bash
   ./venv/bin/pip install -r requirements-dev.txt
   ```

4. **Set up pre-commit hooks:**

   ```bash
   ./venv/bin/pre-commit install
   ```

5. **Copy and configure environment:**

   ```bash
   cp .env.example .env
   # Edit .env with your configuration (demo/paper trading credentials)
   ```

6. **Run tests to verify setup:**

   ```bash
   make test
   ```

## Code Style

We use the following tools to maintain consistent code style:

- **[Ruff](https://docs.astral.sh/ruff/)** for linting
- **[Black](https://black.readthedocs.io/)** for code formatting
- **Line length:** 100 characters
- **Target Python version:** 3.11+

Run the linter and formatter before committing:

```bash
make lint      # Check for lint errors
make format    # Auto-format code
```

### Style Guidelines

- Use type hints for function signatures
- Write docstrings for public functions and classes
- Keep functions focused and under 50 lines where possible
- Use descriptive variable names (no single-letter variables except in comprehensions)
- Add comments for complex trading logic or non-obvious decisions

## Pull Request Process

1. **Fork the repository** and create a feature branch from `main`:

   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Make your changes**, following the code style guidelines above.

3. **Write or update tests** for your changes:

   ```bash
   make test
   ```

4. **Ensure all checks pass:**

   ```bash
   make lint
   make test-coverage
   ```

5. **Push your branch** and open a Pull Request against `main`.

6. **In your PR description**, include:
   - What the change does and why
   - How it was tested
   - Any breaking changes
   - Screenshots or logs if applicable

7. **Address review feedback** promptly. We aim to review PRs within 48 hours.

### PR Requirements

- All tests must pass
- No lint errors
- Code coverage should not decrease
- At least one maintainer approval required
- Squash merge preferred for single-feature PRs

## Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

### Types

| Type       | Description                                      |
| ---------- | ------------------------------------------------ |
| `feat`     | A new feature                                    |
| `fix`      | A bug fix                                        |
| `docs`     | Documentation only changes                       |
| `style`    | Formatting, missing semicolons, etc.             |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf`     | Performance improvement                          |
| `test`     | Adding or updating tests                         |
| `chore`    | Maintenance tasks, dependency updates            |
| `ci`       | CI/CD configuration changes                      |

### Examples

```
feat(strategy): add VWAP crossover day trading strategy
fix(broker): handle IBKR connection timeout gracefully
docs(readme): update installation instructions
refactor(agent): extract risk management into separate module
test(pipeline): add integration tests for signal generation
```

## Questions?

If you have questions about contributing, feel free to open a [Discussion](https://github.com/charleskithika/ai-trading-agent/discussions) or reach out to the maintainers.

Thank you for helping make Joe AI better!
