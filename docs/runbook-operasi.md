# Runbook operasi Platform MAB

Untuk tim yang menjalankan staging/produksi di Kubernetes (Helm chart `infra/helm/mab-platform`) dan untuk uji di
laptop (docker compose). Data rekaan untuk demonstrasi sampai checklist UU PDP disetujui.

Konvensi: namespace `mab-staging`, rilis `mab`. Ganti sesuai lingkungan.

## 1. Target layanan

| Ukuran | Target pilot | Cara diukur |
|---|---|---|
| RPO (data hilang maksimum) | 24 jam dari backup harian; ≤ 5 menit bila PITR database terkelola aktif | CronJob backup + PITR penyedia |
| RTO (waktu pulih) | 2 jam | Uji pemulihan triwulanan (bagian 4) |
| Ketersediaan jam kerja | 99,5% | Alert `MabApiTidakTerjangkau`, uptime check eksternal |
| Retensi backup | 30 hari (`BACKUP_RETENTION_DAYS`), backup terbaru tidak pernah dihapus | Manifest di bucket backup |

## 2. Pemeriksaan harian (5 menit)

1. `kubectl -n mab-staging get pods`: semua `Running`/`Completed`, tidak ada restart beruntun.
2. Job backup semalam sukses: `kubectl -n mab-staging get jobs -l app.kubernetes.io/component=backup`.
3. Alert terbuka di Alertmanager: antrean menumpuk, job gagal, login dikunci banyak.
4. Antrean: `kubectl -n mab-staging exec deploy/mab-api -- python -c "from mab_api.config import get_settings as g; from redis import Redis; from rq import Queue; r=Redis.from_url(g().redis_url); [print(n, Queue(n, connection=r).count, Queue(n, connection=r).failed_job_registry.count) for n in ('claims','underwriting','webhooks')]"`

## 3. Deploy, upgrade, rollback

```
helm upgrade --install mab infra/helm/mab-platform -n mab-staging -f values-staging.yaml --set image.tag=0.8.1
kubectl -n mab-staging rollout status deploy/mab-api
kubectl -n mab-staging logs deploy/mab-api -c migrate        # hasil migrasi
```

- Migrasi berjalan di initContainer API dengan kunci advisory. Bila migrasi gagal, pod baru tidak Ready dan pod lama
  tetap melayani (rolling update `maxUnavailable: 0`).
- **Rollback aplikasi:** `helm rollback mab <revisi> -n mab-staging`. Migrasi skema tidak ikut mundur otomatis; bila
  versi baru mengubah skema secara tidak kompatibel, pulihkan dari backup atau jalankan `alembic downgrade` dengan
  persetujuan tim (selalu backup manual dulu, bagian 4).
- Sebelum upgrade yang mengubah skema: jalankan backup manual.

## 4. Backup dan pemulihan

Isi backup: `pg_dump` format custom + salinan setiap objek dokumen + `manifest.json` (sha256 dump, jumlah baris per
tabel dari snapshot yang sama dengan dump, sha256 setiap objek). Bucket backup terenkripsi (SSE/KMS) dan sebaiknya di
akun/proyek atau region terpisah dengan versioning + object lock.

**Backup manual**

```
kubectl -n mab-staging create job --from=cronjob/mab-backup backup-manual-$(date +%Y%m%d%H%M)
# laptop: docker compose run --rm ops backup
```

**Daftar backup**

```
kubectl -n mab-staging run ops-list --rm -it --restart=Never --image=<registry>/mab-ops:<tag> \
  --overrides='{"spec":{"containers":[{"name":"ops-list","image":"<registry>/mab-ops:<tag>","args":["list"],"envFrom":[{"configMapRef":{"name":"mab-config"}},{"secretRef":{"name":"mab-staging-secrets"}}]}]}}'
# laptop: docker compose run --rm ops list
```

**Pemulihan (selalu ke database KOSONG)**

1. Hentikan penulisan: `kubectl -n mab-staging scale deploy -l app.kubernetes.io/instance=mab --replicas=0`.
2. Buat database baru (mis. `mab_restore_YYYYMMDD`) di PostgreSQL terkelola. Jangan memulihkan di atas database lama;
   skrip menolak database tidak kosong.
3. Jalankan:
   ```
   python3 /ops/mab_backup.py restore latest --target-database-url "postgresql+psycopg://...@.../mab_restore_YYYYMMDD?sslmode=require"
   ```
   (sebagai Job dengan image `mab-ops`; tambahkan `--target-bucket` bila objek dipulihkan ke bucket baru.)
4. Skrip memverifikasi otomatis: jumlah baris setiap tabel dan sha256 setiap objek harus sama dengan manifest.
   Exit code 0 dan `VERIFIKASI COCOK` berarti berhasil. Selain itu, jangan lanjut; eskalasi.
5. Arahkan `DATABASE_URL` di Secret ke database hasil pulihan, `helm upgrade` (atau restart), lalu naikkan replika.
6. Cek manual: login, buka satu klaim dan dokumennya, buka penampil log audit.
7. Catat di log insiden: id backup, waktu mulai/selesai, jumlah baris dan objek.

**Uji pemulihan triwulanan (wajib):** langkah 2–4 ke database dan bucket uji terpisah, tanpa menghentikan produksi.
Catat waktu sebagai bukti RTO.

Hasil uji pertama (sandbox, 5 Nov 2026): database dihapus (`DROP DATABASE`) dan 308 objek dokumen dihapus, lalu
dipulihkan dari backup yang dibuat sambil API tetap menerima 40 permintaan tulis. Verifikasi: 32 tabel, 4.182 baris,
308 objek (21,6 MB) cocok; pulih dalam ±3 detik; login, daftar 40 klaim, unduh PDF, dan render halaman dokumen berhasil.

**Uji di laptop**

```
docker compose run --rm ops backup
docker compose exec postgres psql -U mab -d postgres -c "CREATE DATABASE mab_restore"
docker compose run --rm ops restore latest --target-database-url postgresql+psycopg://mab:mab_dev_password@postgres:5432/mab_restore --target-bucket mab-documents-restore
```

## 5. Insiden umum

| Gejala | Periksa | Tindakan |
|---|---|---|
| Portal tidak bisa dibuka | `kubectl get ingress,pods`; sertifikat (`kubectl describe certificate`) | Restart web; cek cert-manager; cek allowlist IP |
| `/health/ready` 503 | Isi `checks` di respons: database / redis / storage | Cek layanan terkelola, kredensial di Secret, NetworkPolicy egress |
| Antrean menumpuk (`MabAntreanMenumpuk`) | Log worker antrean itu; LLM lambat/kuota habis? | Tambah replika worker antrean tersebut; cek kuota dan status penyedia LLM |
| Job gagal bertambah | `rq info`, log worker (cari `request_id`/`claim_id`) | Perbaiki penyebab, lalu jalankan ulang job gagal dari registry RQ |
| Banyak login dikunci (`MabLoginDikunciBanyak`) | Log audit aksi `LOGIN_FAILED`/`LOGIN_LOCKED`, IP sumber | Bila serangan: blokir IP di ingress/WAF. Bila pengguna sah lupa password: tunggu 15 menit atau hapus kunci `mab:fail:login:<email>` di Redis setelah verifikasi identitas |
| Dokter terkunci PIN | Log audit `SIGN_PIN_FAILED` | Verifikasi identitas dokter; hapus `mab:fail:pin:<user_id>`; atur ulang PIN lewat admin |
| Dugaan kebocoran data | Log audit, log akses ingress | Ikuti prosedur pelanggaran data (checklist UU PDP bagian F): isolasi, rotasi rahasia, notifikasi tertulis maksimal 3×24 jam |

Semua log aplikasi berformat JSON dengan `request_id`. Header `X-Request-ID` di respons API bisa diminta dari pengguna
untuk menelusuri satu permintaan.

## 6. Rotasi rahasia

| Rahasia | Frekuensi | Cara | Dampak |
|---|---|---|---|
| `JWT_SECRET` | 6 bulan atau saat insiden | Ganti di Secret Manager, restart API | Semua pengguna harus login ulang |
| Password database | 6 bulan | Buat password baru di layanan terkelola, ganti `DATABASE_URL`, restart semua Deployment | Singkat saat restart |
| Kunci S3/MinIO | 6 bulan (lebih baik pakai workload identity tanpa kunci) | Buat kunci baru, ganti Secret, restart, cabut kunci lama | Tidak ada |
| `LLM_API_KEY` | Sesuai kebijakan penyedia | Ganti Secret, restart worker | Tidak ada |
| Kunci KMS | Rotasi otomatis tahunan di KMS penyedia | Aktifkan rotasi otomatis | Tidak ada (data lama tetap terbaca) |
| API key integrasi tenant | Saat diminta tenant | Halaman admin tenant | Sistem tenant perlu kunci baru |

## 7. Skala

- API dan web: HPA berdasarkan CPU (lihat `values.yaml`).
- Worker: atur `workers[].replicas` per antrean. Worker klaim butuh ±2 GB RAM per pod karena model OCR.
- Penjadwal laporan: selalu 1 replika.
