PYTHON ?= python

.PHONY: install test run-webhook run-worker build-webhook build-worker

install:
	$(PYTHON) -m pip install -e .[dev]

test:
	$(PYTHON) -m pytest -q

run-webhook:
	uvicorn services.webhook_service.app:app --reload

run-worker:
	uvicorn services.ingestion_worker.app:app --reload

build-webhook:
	docker build -f Dockerfile.webhook -t ci-observability-webhook .

build-worker:
	docker build -f Dockerfile.worker -t ci-observability-worker .

