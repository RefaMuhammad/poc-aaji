# U8 · Infrastruktur cloud dan kesiapan data sungguhan

Data rekaan untuk demonstrasi. Dokumen ini menjelaskan apa yang dibangun di U8, cara men-deploy ke cloud,
dan apa yang masih harus diputuskan sebelum data sungguhan boleh masuk.

Dokumen terkait:

- [Runbook operasi](runbook-operasi.md): deploy, rollback, backup dan pemulihan, insiden, rotasi rahasia
- [Laporan uji keamanan](u8-laporan-uji-keamanan.md): hasil ZAP, pemindaian kode dan dependensi, uji bencana
- [Keputusan residensi data LLM](u8-residensi-llm.md): pilihan model dan lokasi pemrosesan
- [Checklist UU PDP](u8-checklist-uu-pdp.md): gerbang sebelum data sungguhan

## Ringkasan

| Cakupan rencana | Status | Di mana |
|---|---|---|
| Manifest Kubernetes/Helm | Selesai, lolos `helm lint` dan validasi server Kubernetes | `infra/helm/mab-platform` |
| Deploy ke cloud pilihan | Chart netral siap pakai. Deploy staging menunggu penyedia cloud dan akun dari klien | `values-staging.yaml` |
| TLS | Ingress dengan cert-manager (Let's Encrypt), paksa HTTPS, HSTS dari aplikasi | `templates/ingress.yaml` |
| Enkripsi data at rest | MinIO SSE-S3 aktif dan terbukti (berkas di disk tidak terbaca). S3 SSE-KMS siap. Database: layanan terkelola terenkripsi + TLS wajib untuk data sungguhan | `storage.py`, `.env.example` |
| Backup dan pemulihan | Skrip backup/restore/verify, CronJob harian, uji bencana lolos | `infra/ops/mab_backup.py` |
| Monitoring dan log terpusat | `/metrics` Prometheus, alert, `/health/ready`, log JSON dengan request id | `observability.py`, `templates/monitoring.yaml` |
| Uji penetrasi | Uji otomatis internal lolos (ZAP, bandit, pip-audit, npm audit, tes keamanan). Uji penetrasi pihak ketiga tetap wajib sebelum data sungguhan | laporan uji keamanan |
| Keputusan residensi data LLM | Pilihan dan rekomendasi ditulis. Keputusan ada di klien + tim hukum. Kode menolak data sungguhan sampai keputusan disetujui | `u8-residensi-llm.md` |

## Arsitektur di Kubernetes

```
Internet ─▶ Ingress (TLS, allowlist IP staging) ─▶ web (Next.js, 2+ pod)
                                                     │  /api/* (proxy)
                                                     ▼
                         ┌──────────────── api (FastAPI, 2–6 pod, initContainer migrasi)
                         │                    │
                 Redis (antrean)        PostgreSQL terkelola (TLS)      S3/GCS/Blob (SSE-KMS)
                         │                    ▲                                ▲
   worker-claims ◀───────┤                    │                                │
   worker-underwriting ◀─┤  (OCR + LLM)  ─────┴────────────────────────────────┘
   worker-webhooks ◀─────┘
   report-scheduler (1 pod)        CronJob backup (harian 01.00 WIB) ─▶ bucket backup
```

- **Satu chart, netral penyedia.** Database, Redis, dan penyimpanan objek memakai layanan terkelola penyedia cloud
  (region Jakarta/Indonesia). Untuk uji lokal, `values-local.yaml` menyalakan PostgreSQL, Redis, dan MinIO di dalam klaster.
- **Worker per antrean.** Klaim, underwriting, dan webhook punya antrean dan Deployment sendiri (`RQ_QUEUES`), sehingga
  lonjakan underwriting tidak menahan klaim. Di laptop satu worker tetap mendengarkan semua antrean.
- **Migrasi aman.** initContainer `python -m mab_api.migrate` memakai kunci advisory PostgreSQL, jadi beberapa pod API
  yang start bersamaan tidak menjalankan migrasi ganda.
- **Pod dikunci.** Semua container jalan non-root (UID 10001), tanpa capability, `readOnlyRootFilesystem` (kecuali worker
  OCR), seccomp `RuntimeDefault`, token service account tidak dipasang.
- **NetworkPolicy.** Bawaan menolak semua trafik masuk; hanya ingress controller ke web, web ke API, dan Prometheus ke
  `/metrics` yang dibuka. API integrasi (`/integrations/v1`) hanya dibuka bila `ingress.apiHost` diisi.
- **Ketersediaan.** HPA untuk API dan web, PodDisruptionBudget, rolling update tanpa downtime, topology spread.

## Gerbang konfigurasi (dipaksa oleh kode)

Bila `ENVIRONMENT` bukan `development`, API, worker, dan migrasi **menolak start** kalau:

- `JWT_SECRET` masih bawaan atau kurang dari 32 karakter
- password database atau MinIO masih password dev
- `LOG_FORMAT` bukan `json`
- `CORS_ORIGINS` memuat origin `http://` selain localhost

Bila `REAL_DATA_ENABLED=true`, syarat tambahan: environment `production`, `DEMO_MODE=false`, LLM bukan mock,
`LLM_DATA_RESIDENCY_APPROVED=true`, `S3_SSE` diisi, dan `DATABASE_URL` memakai `sslmode=require`/`verify-full`.
Item checklist UU PDP lain (DPIA, kontrak, DPO, uji penetrasi pihak ketiga) adalah keputusan organisasi dan tidak bisa
dicek oleh kode; itu sebabnya `REAL_DATA_ENABLED` hanya boleh diubah setelah checklist ditandatangani.

## Perubahan aplikasi di U8

| Area | Perubahan |
|---|---|
| Keamanan login | Batas 5 kali gagal per akun dalam 15 menit (lalu 429 + `Retry-After`), 100 kali per IP. Tercatat di log audit (`LOGIN_LOCKED`) |
| PIN tanda tangan | Batas 5 kali PIN salah per dokter, berlaku untuk klaim dan underwriting |
| Header | API: `nosniff`, `X-Frame-Options`, CSP ketat, `Referrer-Policy`, `Cache-Control: no-store`, HSTS di luar dev. Web: CSP dengan nonce per permintaan (`middleware.ts`), tanpa `X-Powered-By` |
| Health | `/health/live` (proses hidup) dan `/health/ready` (database, Redis, penyimpanan) |
| Metrik | `/metrics`: jumlah dan latensi permintaan per pola rute (tanpa id), panjang antrean, job gagal, penguncian login |
| Log | `LOG_FORMAT=json`: satu baris JSON per permintaan dengan `request_id`, rute, status, durasi, IP. Isi dokumen dan data medis tidak pernah ditulis ke log |
| Penyimpanan | `S3_SSE` (`AES256`/`aws:kms`), `S3_KMS_KEY_ID`, bucket baru diberi enkripsi bawaan, endpoint/kredensial kosong = IAM cloud |
| Image | Non-root; image `ops` baru untuk backup |
| Dependensi | Next.js 14 → 15.5 (React 19), FastAPI/Starlette, PyJWT, Pillow, pdfplumber/pypdfium2, python-multipart, Jinja2, fpdf2, WeasyPrint diperbarui karena celah keamanan |

## Men-deploy staging (setelah penyedia cloud dipilih)

1. **Siapkan layanan terkelola di region Indonesia/Jakarta:** klaster Kubernetes, PostgreSQL 16 (enkripsi at rest, TLS,
   backup otomatis + PITR), Redis (TLS bila tersedia), dua bucket (dokumen dan backup) dengan enkripsi KMS dan
   versioning, kunci KMS, registry image, Secret Manager.
2. **Pasang add-on klaster:** ingress-nginx, cert-manager dengan ClusterIssuer `letsencrypt`, External Secrets Operator,
   kube-prometheus-stack (opsional tapi disarankan), agen log penyedia cloud.
3. **Bangun dan dorong image** (dari root repo):
   ```
   docker build -f infra/docker/api.Dockerfile -t <registry>/mab-api:0.8.0 .
   docker build -f infra/docker/worker.Dockerfile -t <registry>/mab-worker:0.8.0 .
   docker build -f infra/docker/web.Dockerfile -t <registry>/mab-web:0.8.0 .
   docker build -f infra/docker/ops.Dockerfile -t <registry>/mab-ops:0.8.0 .
   docker build -f infra/docker/synthetic.Dockerfile -t <registry>/mab-synthetic:0.8.0 .
   docker push <registry>/mab-api:0.8.0   # dan seterusnya
   ```
4. **Isi rahasia** di Secret Manager lalu sinkronkan ke Secret `mab-staging-secrets` (kunci: lihat `secrets` di
   `values.yaml`). Buat `JWT_SECRET` acak 64 karakter.
5. **Salin `values-staging.yaml`**, ganti semua nilai bertanda "ganti", lalu
   `helm upgrade --install mab infra/helm/mab-platform -n mab-staging --create-namespace -f values-staging.yaml`.
6. **Cek:** semua pod Ready, `https://<host>/login` terbuka dengan sertifikat valid, Job seed selesai, CronJob backup
   terjadwal. Jalankan uji pemulihan pertama (runbook bagian 4) dan ZAP terhadap URL staging.

Nilai per penyedia (contoh, region Indonesia):

| | GCP | AWS | Azure |
|---|---|---|---|
| Region | asia-southeast2 (Jakarta) | ap-southeast-3 (Jakarta) | Indonesia Central |
| Klaster | GKE | EKS | AKS |
| PostgreSQL | Cloud SQL | RDS | Azure Database for PostgreSQL |
| Redis | Memorystore | ElastiCache | Azure Cache for Redis |
| Dokumen | GCS (interop S3 + CMEK) | S3 + SSE-KMS | Blob lewat gateway S3 atau MinIO + Key Vault |
| Rahasia | Secret Manager | Secrets Manager | Key Vault |
| Identitas pod | Workload Identity | IRSA / Pod Identity | Workload Identity |
| Log | Cloud Logging | CloudWatch | Azure Monitor |

Cek ketersediaan layanan di region tersebut saat penyedia dipilih; daftar ini belum diverifikasi per layanan.

## Uji di sandbox pengembangan

- `helm lint` (3 set nilai) dan `kubectl apply --dry-run=server` ke API server Kubernetes 1.30: 22 objek staging,
  22 objek lokal, dan CRD ServiceMonitor/PrometheusRule diterima.
- Pod tidak bisa dijalankan di sandbox (runtime container bersarang ditolak), jadi uji jalan aplikasi dilakukan dengan
  PostgreSQL 16, Redis, dan MinIO di Docker + API, worker, dan web dari kode ini. Uji jalan chart di klaster sungguhan
  menjadi langkah pertama staging.
- Image `ops` dan perubahan Dockerfile tidak bisa di-build di sandbox (repo paket Debian/Alpine diblokir jaringan
  sandbox); skrip backup diuji langsung dengan `pg_dump` 16. Build image pertama dilakukan di laptop atau CI.

## Belum termasuk

- Deploy ke akun cloud sungguhan (butuh pilihan penyedia dan akses dari klien).
- Uji penetrasi oleh pihak ketiga independen.
- CI/CD (build image otomatis, scan image dengan Trivy, deploy ke staging). Disarankan sebagai langkah setelah U8.
- Dashboard Grafana. Metrik dan alert sudah ada; dashboard dibuat setelah Prometheus staging jalan.
