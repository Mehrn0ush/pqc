.PHONY: install test lint validate build serve check-links

install:
	python -m venv .venv && .venv/bin/pip install -r requirements-dev.lock && .venv/bin/pip install --no-deps -e .

test:
	.venv/bin/python -m unittest discover -s tests

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

validate:
	.venv/bin/pqc-tracker validate

build: validate
	.venv/bin/pqc-tracker build --out dist/site

serve: build
	python3 -m http.server 8080 --directory dist/site

check-links:
	.venv/bin/pqc-tracker check-links
