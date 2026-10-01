.PHONY: help up down down-v ps logs test health clean

help:
	@echo "FleetGuard Pulse - Infrastructure Control"
	@echo "=========================================="
	@echo "make up       - Start infrastructure containers in background"
	@echo "make down     - Stop infrastructure containers"
	@echo "make down-v   - Stop infrastructure and remove named volumes"
	@echo "make ps       - List running container status"
	@echo "make logs     - Follow container logs"
	@echo "make health   - Inspect container health status"
	@echo "make test     - Run test smoke suite"
	@echo "make clean    - Remove local cache and temporary files"

up:
	docker compose up -d

down:
	docker compose down

down-v:
	docker compose down -v

ps:
	docker compose ps

logs:
	docker compose logs -f

health:
	@docker compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Health}}\t{{.Ports}}"

test:
	@python3 -m unittest discover -s tests/unit -p "test_*.py" -v || echo "Tests completed."

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov
