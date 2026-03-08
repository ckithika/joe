.PHONY: install install-dev test test-coverage lint format pipeline monitor monitor-crypto bot dashboard setup clean docker-build docker-run

VENV := ./venv/bin

install:
	$(VENV)/pip install -r requirements.txt

install-dev:
	$(VENV)/pip install -r requirements-dev.txt
	$(VENV)/pre-commit install

test:
	$(VENV)/pytest tests/

test-coverage:
	$(VENV)/pytest tests/ --cov=agent --cov-report=term-missing --cov-report=html

lint:
	$(VENV)/ruff check .
	$(VENV)/mypy agent/ --ignore-missing-imports

format:
	$(VENV)/ruff check --fix .
	$(VENV)/black .

pipeline:
	$(VENV)/python3 main.py --once --push

monitor:
	$(VENV)/python3 monitor.py

monitor-crypto:
	$(VENV)/python3 monitor.py --crypto

bot:
	$(VENV)/python3 telegram_bot.py

dashboard:
	$(VENV)/streamlit run dashboard.py

setup:
	python3 -m venv venv
	$(VENV)/pip install --upgrade pip
	$(VENV)/pip install -r requirements-dev.txt
	$(VENV)/pre-commit install
	@echo "Setup complete. Activate with: source venv/bin/activate"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage .mypy_cache .ruff_cache
	rm -rf dist build *.egg-info

docker-build:
	docker build -t joe-ai .

docker-run:
	docker run --env-file .env joe-ai
