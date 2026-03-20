SHELL := /bin/bash

ENV_FILE ?= $(HOME)/.isilon_discovery.env
INVENTORY ?= inventory.yaml
DB_PATH ?= shares.db
DOCKER_NODE ?=

.PHONY: setup test discovery webapp run docker-build docker-discovery docker-webapp docker-shell

setup:
	python -m venv .venv || true
	./.venv/bin/pip install --upgrade pip setuptools wheel
	./.venv/bin/pip install -r requirements.txt

test:
	./.venv/bin/python -m pytest -q

discovery:
	./.venv/bin/python -m isilon_discovery --inventory "$(INVENTORY)"

webapp:
	./.venv/bin/python -m flask --app webapp.app run --debug

run: discovery

docker-build:
	docker build -t isilon-discovery:latest .

docker-discovery:
	docker run --rm \
		-v "$(PWD)":/app -w /app \
		-e "ISILON_ENV_FILE=/root/.isilon_discovery.env" \
		-v "$(ENV_FILE)":/root/.isilon_discovery.env:ro \
		isilon-discovery:latest --inventory "$(INVENTORY)" $(DOCKER_NODE)

docker-webapp:
	docker run --rm -p 5000:5000 \
		-v "$(PWD)":/app -w /app \
		-e "ISILON_ENV_FILE=/root/.isilon_discovery.env" \
		-v "$(ENV_FILE)":/root/.isilon_discovery.env:ro \
		-e "DB_PATH=$(DB_PATH)" \
		--entrypoint python \
		isilon-discovery:latest \
		-m flask --app webapp.app run --host 0.0.0.0 --port 5000 --debug

docker-shell:
	docker run --rm -it \
		-v "$(PWD)":/app -w /app \
		-e "ISILON_ENV_FILE=/root/.isilon_discovery.env" \
		-v "$(ENV_FILE)":/root/.isilon_discovery.env:ro \
		--entrypoint sh \
		isilon-discovery:latest sh

