.PHONY: up down migrate test sim load k6 demo logs

up:
	docker compose up --build -d
	@echo "API http://localhost:8000  UI http://localhost:5173  Mock http://localhost:8001"

down:
	docker compose down -v

migrate:
	cd backend && python -m tortoise -c app.db.config.TORTOISE_ORM migrate || true
	cd backend && python -c "import asyncio; from app.db.bootstrap import init_db; asyncio.run(init_db())"

test:
	cd backend && pytest -q

sim:
	cd backend && python -m app.workers.sim --scenario $${SCENARIO:-B}

load:
	cd backend && python -m app.workers.load_harness --agents $${AGENTS:-100}

k6:
	k6 run load/k6_webhook.js

demo:
	./scripts/demo.sh

logs:
	docker compose logs -f --tail=100
