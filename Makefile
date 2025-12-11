.PHONY: help install dev test migrate clean superuser

help:
	@echo "PulseGuard Backend - Available Commands"
	@echo "======================================"
	@echo "make install      - Install dependencies"
	@echo "make dev          - Run development server"
	@echo "make migrate      - Run database migrations"
	@echo "make makemigrations - Create new migrations"
	@echo "make superuser    - Create superuser"
	@echo "make test         - Run tests"
	@echo "make clean        - Remove .pyc files and cache"
	@echo "make freeze       - Update requirements.txt"

install:
	pip install -r requirements.txt

dev:
	ENVIRONMENT=development python manage.py runserver

migrate:
	ENVIRONMENT=development python manage.py migrate

makemigrations:
	ENVIRONMENT=development python manage.py makemigrations

superuser:
	ENVIRONMENT=development python manage.py createsuperuser

test:
	ENVIRONMENT=development python manage.py test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".DS_Store" -delete

freeze:
	pip freeze > requirements.txt
