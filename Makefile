SHELL := /bin/bash

COMPOSE ?= docker compose

.PHONY: build up down logs ps-run

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

ps-run:
	$(COMPOSE) --profile ps run --rm ps
