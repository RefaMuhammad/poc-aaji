#!/usr/bin/env bash
# Kosongkan SEMUA data aplikasi (database + file dokumen), nyalakan ulang, lalu isi data demo.
# DATA REKAAN saja. Pemakaian: bash infra/scripts/reset_demo.sh   (atau: make reset)
# Lewati konfirmasi dengan RESET_YES=1.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ "${RESET_YES:-0}" != "1" ]; then
  read -r -p "Semua klaim, dokumen, telaah, dan log audit di database lokal akan DIHAPUS. Lanjut? [y/N] " answer
  case "$answer" in y|Y|ya|YA) ;; *) echo "Dibatalkan."; exit 1;; esac
fi

[ -f .env ] || cp .env.example .env

if [ ! -f data/synthetic_output/kunci_jawaban.csv ]; then
  echo "== Membuat data sintetis (sekali saja)"
  docker compose run --rm --build synthetic
fi

echo "== Mematikan service dan menghapus volume database + MinIO"
docker compose down -v

echo "== Menyalakan ulang"
docker compose up -d --build

echo "== Menunggu API siap"
for i in $(seq 1 90); do
  if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then
    break
  fi
  sleep 2
  if [ "$i" = "90" ]; then echo "API belum siap. Cek: docker compose logs api"; exit 1; fi
done

echo "== Mengisi data demo"
docker compose exec -T api python infra/scripts/seed_demo.py
