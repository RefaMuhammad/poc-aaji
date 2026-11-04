.PHONY: help env up down logs test synthetic seed-users seed reset eval eval-extraction eval-triage

help:
	@echo "Perintah: make env | up | down | logs | test | synthetic | seed-users | seed | reset | eval | eval-extraction | eval-triage"

env:
	@test -f .env || cp .env.example .env && echo ".env siap"

up: env
	docker compose up -d --build
	@echo "API: http://localhost:8000/health  |  Web: http://localhost:3000  |  MinIO API: http://localhost:9000"

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

test: env
	docker compose run --rm --no-deps api pytest -q tests

synthetic: env
	docker compose run --rm --build synthetic

seed-users:
	docker compose exec api python infra/scripts/seed_users.py

seed:
	@echo "make seed belum diimplementasi (dijadwalkan di M8)."

reset:
	@echo "make reset belum diimplementasi (dijadwalkan di M8)."

# Akurasi ekstraksi M4 terhadap ground_truth.json (butuh `make synthetic` dulu).
# Pakai LLM_PROVIDER di .env; hasil di evaluation/reports/.
eval-extraction: env
	docker compose run --rm --no-deps worker python -m evaluation.extraction_accuracy

# Triase dan rekomendasi M5 terhadap kunci_jawaban.csv (butuh `make synthetic` dulu).
eval-triage: env
	docker compose run --rm --no-deps worker python -m evaluation.triage_accuracy

eval:
	@echo "make eval belum diimplementasi (dijadwalkan di M8)."
