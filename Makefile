.PHONY: help install run test lint data up down logs producer consumer carbon-scheduler ml-trainer up-prod up-monitoring

help:
	@echo "iEMS targets:"
	@echo "  make install           - install Python package with dev extras"
	@echo "  make run               - run FastAPI locally"
	@echo "  make producer          - run 1 Hz Kafka producer"
	@echo "  make consumer          - run Kafka -> TimescaleDB consumer"
	@echo "  make carbon-scheduler  - run Scope 1/2 report scheduler"
	@echo "  make ml-trainer        - train ELM/LSTM and register models"
	@echo "  make test              - run unit/API tests"
	@echo "  make up                - start Docker Compose stack"
	@echo "  make up-monitoring     - add Prometheus/Grafana/Alertmanager + DB backup"
	@echo "  make up-prod           - prod overlay (AUTH_ENFORCE) + monitoring + backup"
	@echo "  make down              - stop Docker Compose stack"

install:
	python -m pip install -U pip
	pip install -e ".[dev]"

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

producer:
	python -m app.ingestion.producer

consumer:
	python -m app.ingestion.consumer

carbon-scheduler:
	python -m app.carbon.scheduler

ml-trainer:
	python -m app.ml.trainer

test:
	pytest -q

lint:
	ruff check app scripts tests

data:
	python -m scripts.generate_synthetic_data

up:
	docker compose up -d --build

up-monitoring:
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d --build

up-prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.monitoring.yml up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api producer consumer carbon-scheduler ml-trainer
