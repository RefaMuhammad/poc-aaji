.PHONY: help env up down logs test synthetic seed-users seed reset eval eval-extraction eval-triage eval-underwriting backup backups

help:
	@echo "Perintah: make env | up | down | logs | test | synthetic | seed-users | seed | reset | eval | eval-extraction | eval-triage | eval-underwriting | backup | backups"

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

# Isi data demo ke database yang sedang jalan (butuh `make up` dan `make synthetic`).
seed:
	docker compose exec api python infra/scripts/seed_demo.py

# Kosongkan semua data lalu isi ulang data demo (minta konfirmasi).
reset:
	bash infra/scripts/reset_demo.sh

# Akurasi ekstraksi M4 terhadap ground_truth.json (butuh `make synthetic` dulu).
# Pakai LLM_PROVIDER di .env; hasil di evaluation/reports/.
eval-extraction: env
	docker compose run --rm --no-deps worker python -m evaluation.extraction_accuracy

# Triase dan rekomendasi M5 terhadap kunci_jawaban.csv (butuh `make synthetic` dulu).
eval-triage: env
	docker compose run --rm --no-deps worker python -m evaluation.triage_accuracy

# Evaluasi lengkap Tahap 0 (ekstraksi, triase, hijau keliru, waktu proses) -> evaluation/reports/eval_*.md
eval: env
	docker compose run --rm --no-deps worker python -m evaluation.run_eval

# U7: akurasi kelas risiko underwriting atas 35 kasus sintetis -> evaluation/reports/underwriting_*.md
eval-underwriting: env
	docker compose run --rm --no-deps worker python -m evaluation.underwriting_eval

# U8: backup database + dokumen ke bucket mab-backups di MinIO lokal (lihat docs/runbook-operasi.md)
backup: env
	docker compose run --rm ops backup

backups: env
	docker compose run --rm ops list
