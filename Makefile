.PHONY: help install run test lint data up down logs producer consumer carbon-scheduler ml-trainer up-prod up-monitoring up-demo up-ha demo demo-feeder plant-connect soak backup restore-dry-run e11-checklist

help:
	@echo "iEMS targets:"
	@echo "  make install           - install Python package with dev extras"
	@echo "  make run               - run FastAPI locally"
	@echo "  make demo              - live dashboard with inline memory feeder (no Docker)"
	@echo "  make demo-feeder       - standalone 1 Hz feeder (memory/DB)"
	@echo "  make plant-connect     - print Plant Connect env checklist"
	@echo "  make soak              - E6 1 Hz soak on olefin/pta (simulator or OPC)"
	@echo "  make producer          - run 1 Hz Kafka producer"
	@echo "  make consumer          - run Kafka -> TimescaleDB consumer"
	@echo "  make carbon-scheduler  - run Scope 1/2 report scheduler"
	@echo "  make ml-trainer        - train ELM/LSTM and register models"
	@echo "  make test              - run unit/API tests"
	@echo "  make up                - start full Docker Compose stack"
	@echo "  make up-demo           - Timescale + Redis + API feeder (no Kafka)"
	@echo "  make up-monitoring     - add Prometheus/Grafana/Alertmanager + DB backup"
	@echo "  make up-prod           - prod overlay (AUTH_ENFORCE) + monitoring + backup"
	@echo "  make up-ha             - prod + monitoring + api-b HA profile"
	@echo "  make backup            - local TimescaleDB pg_dump (needs psql/pg_dump)"
	@echo "  make restore-dry-run   - gzip-test latest backup without applying"
	@echo "  make e11-checklist     - print E11 Enterprise Ops cutover checklist"
	@echo "  make down              - stop Docker Compose stack"

install:
	python -m pip install -U pip
	pip install -e ".[dev]"

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

demo:
	DEMO_FEEDER=true DEMO_MEMORY_ONLY=true DEMO_PREFER_MEMORY=true PRODUCER_PLANT_CODES=olefin,pta uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

demo-feeder:
	DEMO_MEMORY_ONLY=true PRODUCER_PLANT_CODES=olefin,pta python -m app.demo.feeder

plant-connect:
	@echo "E6 Plant Connect checklist:"
	@echo "  1. Edit infra/opcua/tags.yaml with real NodeIds"
	@echo "  2. Apply migrate: infra/db/migrate_e6.sql"
	@echo "  3. export PLANT_CONNECT=true INGESTION_SOURCE=opcua"
	@echo "  4. export OPC_UA_ENDPOINT=opc.tcp://host:4840"
	@echo "  5. pip install 'iems[opcua]'"
	@echo "  6. make producer && make consumer"
	@echo "  7. make soak"

soak:
	python -m scripts.plant_connect_soak --seconds 20 --plants olefin,pta

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

up-demo:
	docker compose -f docker-compose.demo.yml up -d --build

up-monitoring:
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d --build

up-prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.monitoring.yml up -d --build

up-ha:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.monitoring.yml --profile ha up -d --build

backup:
	bash scripts/backup_local.sh

restore-dry-run:
	@LATEST=$$(ls -1t data/backups/iems_*.sql.gz 2>/dev/null | head -n 1); \
	if [ -z "$$LATEST" ]; then echo "No backups in data/backups/"; exit 1; fi; \
	DRY_RUN=1 bash scripts/restore_timescaledb.sh "$$LATEST"

e11-checklist:
	@echo "E11 Enterprise Ops checklist:"
	@echo "  1. export SECRET_KEY=... AUTH_ENFORCE=true"
	@echo "  2. OIDC: OIDC_ENABLED=true OIDC_ISSUER=... OIDC_CLIENT_ID=... OIDC_CLIENT_SECRET=..."
	@echo "     (local stand-in: OIDC_DEV_BYPASS=true APP_DEBUG=true → POST /api/v1/auth/oidc/dev-login)"
	@echo "  3. Apply migrate: infra/db/migrate_e11.sql (sites)"
	@echo "  4. make up-prod   # or make up-ha for api-b"
	@echo "  5. Wire Alertmanager: copy infra/monitoring/alertmanager.oncall.example.yml"
	@echo "  6. Verify: curl /api/v1/ops/status  and Grafana SLO panels"
	@echo "  7. DR drill: make backup && make restore-dry-run"
	@echo "  8. Confirm AUTH_ENFORCE=true and 24x7 webhook receiver"

down:
	docker compose down

logs:
	docker compose logs -f api producer consumer carbon-scheduler ml-trainer
