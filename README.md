# XPostDeleter

**[English](#english) | [Bahasa Indonesia](#bahasa-indonesia)**

---

<a name="english"></a>
## English

### What is this?

XPostDeleter scans your X (Twitter) archive and automatically deletes posts that contain **your face**, **NSFW content**, or **specific keywords** — your personal "black history" eraser.

**How it works:**
1. `archive_scanner.py` — reads your X archive, detects faces/NSFW with AI and/or scans text with LLM, outputs `delete_hit_list.csv`
2. `delete_agent.py` — reads the CSV and deletes each post via Selenium with human-like mouse movement to avoid bot detection

### Features

- Face detection with [InsightFace](https://github.com/deepinsight/insightface) — matches your face against reference selfies
- NSFW detection with [NudeNet](https://github.com/notAI-tech/NudeNet)
- 3-stage text analysis (`--text`): keyword match → Gemini → Claude
- Human-like mouse movement (Bézier curve + easing + jitter) to reduce bot detection risk
- Checkpoint saving — progress is written to CSV after every deletion, safe to resume
- RT (repost) handling — reposts are separated to `rt_hit_list.csv` and processed separately
- Progress display with severity filtering

### Requirements

- Python 3.11+
- Google Chrome + matching [ChromeDriver](https://googlechromelabs.github.io/chrome-for-testing/)
- GPU recommended (CUDA) for InsightFace — CPU works but is slow
- Gemini API key (free tier is sufficient) for text analysis

### Setup

#### 1. Clone & create virtual environment

```bash
git clone https://github.com/yourname/XPostDeleter.git
cd XPostDeleter
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

#### 2. Install dependencies

```bash
pip install -r requirements.txt
```

#### 3. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Chrome user data directory
USER_DATA_DIR=C:\Users\YourName\AppData\Local\Google\Chrome\User Data

# Required only for --text mode
GEMINI_API_KEY=your_gemini_api_key_here

# Optional — used for borderline cases escalated from Gemini
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

#### 4. Add reference selfies

Place **2–5 clear selfies of yourself** in `reference_media/`. These are used by InsightFace to recognize your face in archive images.

```
reference_media/
  selfie1.jpg
  selfie2.jpg
```

> `reference_media/` is in `.gitignore` — your photos will never be committed.

#### 5. (Optional) Configure keywords for text analysis

```bash
cp keywords.json.example keywords.json
```

Edit `keywords.json` to add the words you want to detect in tweet text. Three severity tiers are supported:

```json
{
  "high":   ["word that must go"],
  "medium": ["word that should go"],
  "low":    ["word to consider"]
}
```

> `keywords.json` is in `.gitignore` — your personal keyword list will never be committed.

---

### Step 1 — Prepare your X Archive

1. Go to **X Settings → Your account → Download an archive of your data**
2. Wait for the email, download and extract the zip
3. Place the extracted folder as `XArchive/` in the project root:

```
XPostDeleter/
  XArchive/
    data/
      tweets.js
      tweets_media/
        12345678-photo.jpg
        ...
```

---

### Step 2 — Generate the delete list

#### Image / video scan only (default)

Detects posts with your face or NSFW content:

```bash
python archive_scanner.py
```

> If `delete_hit_list.csv` already exists, image/video analysis is automatically skipped — only new tweets are processed.

#### Image + text analysis

Also scans all tweet text with keyword matching and LLM judgment:

```bash
python archive_scanner.py --text
```

**Text analysis pipeline (`--text`):**

| Stage | Engine | When used |
|-------|--------|-----------|
| 1 — Keyword | local `keywords.json` | always (instant, free) |
| 2 — Gemini | Gemini API (free tier) | tweets that pass keyword filter |
| 3 — Claude | Claude API (optional) | tweets Gemini rates as uncertain |

> The Gemini free tier (15 RPM) is sufficient. A 10,000-tweet archive takes roughly 30 minutes for text analysis.

This creates (or updates) `delete_hit_list.csv`:

| Column | Description |
|--------|-------------|
| `created_at` | Post timestamp |
| `delete_url` | URL of the post |
| `severity` | Risk score 0–5 |
| `risk_tags` | e.g. `FACE_SELFIE`, `NSFW_HIGH`, `TEXT_KEYWORD`, `TEXT_GEMINI` |
| `full_text` | Post text |
| `hapus` | Deletion status (empty = pending, `sudah` = done) |

**Always review the CSV and remove any rows you want to keep before proceeding.**

---

### Step 3 — Run the delete agent

#### Option A — Attach to an already-running Chrome

1. Close all Chrome windows, then launch Chrome with remote debugging:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:USER_DATA_DIR" `
  --profile-directory="Default"
```

2. Log in to X manually in that Chrome window.

3. Run the agent:

```bash
python delete_agent.py --attach-existing --limit 50
```

#### Option B — Let Selenium launch Chrome automatically

```bash
python delete_agent.py --limit 50
```

#### Key options

| Option | Default | Description |
|--------|---------|-------------|
| `--limit N` | 50 | Max posts to delete per run |
| `--allow-low-severity` | off | Also delete severity < 1 posts |
| `--attach-existing` | off | Attach to running Chrome on port 9222 |
| `--rt` | off | Process `rt_hit_list.csv` (unretweet mode) |
| `--log-file PATH` | `xpostdeleter.log` | Log file path |
| `--debug-rt` | off | Verbose RT/repost detection logging |

---

### Project structure

```
XPostDeleter/
  delete_agent.py        # Entry point (CLI)
  actions.py             # Delete / unretweet routines
  browser.py             # ChromeDriver factory & navigation
  human.py               # Human-like mouse, scroll, timing
  utils.py               # Logging tee & progress bar
  archive_scanner.py     # Archive scan → delete_hit_list.csv
  image_analyzer.py      # Face recognition & NSFW detection
  text_analyzer.py       # 3-stage text analysis (keyword / Gemini / Claude)
  keywords.json.example  # Keyword list template (copy to keywords.json)
  .env.example           # Environment variable template
  requirements.txt       # Python dependencies
```

### Disclaimer

> **Read carefully before use.**

- This tool is for **personal use only** — deleting your own posts.
- Automated browser interaction may violate X's Terms of Service — **use at your own risk**.
- During execution, **do not touch the mouse** (pyautogui controls it).
- Keep batch sizes reasonable (20–50 per run) to reduce detection risk.
- **AI detection (image, NSFW, and text) is not perfect.** False positives will occur — posts that have nothing to do with your intended targets may end up on the delete list. **Always review `delete_hit_list.csv` before running the delete agent.** The authors take no responsibility for any posts deleted as a result of false positives or misdetection.

---
---

<a name="bahasa-indonesia"></a>
## Bahasa Indonesia

### Apa ini?

XPostDeleter memindai arsip X (Twitter) kamu dan secara otomatis menghapus postingan yang mengandung **wajahmu**, **konten NSFW**, atau **kata kunci tertentu** — penghapus "jejak digital memalukan" pribadimu.

**Cara kerjanya:**
1. `archive_scanner.py` — membaca arsip X, mendeteksi wajah/NSFW dengan AI dan/atau memindai teks dengan LLM, menghasilkan `delete_hit_list.csv`
2. `delete_agent.py` — membaca CSV dan menghapus setiap postingan lewat Selenium dengan gerakan mouse seperti manusia untuk menghindari deteksi bot

### Fitur

- Deteksi wajah dengan [InsightFace](https://github.com/deepinsight/insightface) — mencocokkan wajahmu dengan foto referensi selfie
- Deteksi NSFW dengan [NudeNet](https://github.com/notAI-tech/NudeNet)
- Analisis teks 3 tahap (`--text`): pencocokan keyword → Gemini → Claude
- Gerakan mouse seperti manusia (kurva Bézier + easing + jitter) untuk mengurangi risiko deteksi bot
- Penyimpanan checkpoint — progres ditulis ke CSV setelah setiap penghapusan, aman untuk dilanjutkan
- Penanganan RT (repost) — repost dipisah ke `rt_hit_list.csv` dan diproses terpisah
- Tampilan progres dengan filter tingkat keparahan

### Persyaratan

- Python 3.11+
- Google Chrome + [ChromeDriver](https://googlechromelabs.github.io/chrome-for-testing/) yang sesuai
- GPU direkomendasikan (CUDA) untuk InsightFace — CPU bisa tapi lambat
- Gemini API key (tier gratis sudah cukup) untuk analisis teks

### Persiapan

#### 1. Clone & buat virtual environment

```bash
git clone https://github.com/yourname/XPostDeleter.git
cd XPostDeleter
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

#### 2. Install dependensi

```bash
pip install -r requirements.txt
```

#### 3. Konfigurasi `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Direktori data pengguna Chrome
USER_DATA_DIR=C:\Users\NamaKamu\AppData\Local\Google\Chrome\User Data

# Wajib hanya untuk mode --text
GEMINI_API_KEY=your_gemini_api_key_here

# Opsional — digunakan untuk kasus meragukan yang dieskalasi dari Gemini
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

#### 4. Tambahkan foto selfie referensi

Taruh **2–5 selfie yang jelas dari dirimu** di folder `reference_media/`. Ini digunakan InsightFace untuk mengenali wajahmu di foto-foto arsip.

```
reference_media/
  selfie1.jpg
  selfie2.jpg
```

> `reference_media/` ada di `.gitignore` — foto-foto kamu tidak akan pernah ikut ter-commit.

#### 5. (Opsional) Konfigurasi keyword untuk analisis teks

```bash
cp keywords.json.example keywords.json
```

Edit `keywords.json` untuk menambahkan kata-kata yang ingin kamu deteksi di teks tweet. Tersedia tiga tingkat keparahan:

```json
{
  "high":   ["kata yang harus dihapus"],
  "medium": ["kata yang sebaiknya dihapus"],
  "low":    ["kata yang perlu dipertimbangkan"]
}
```

> `keywords.json` ada di `.gitignore` — daftar keyword pribadimu tidak akan pernah ikut ter-commit.

---

### Langkah 1 — Siapkan Arsip X

1. Buka **X Settings → Your account → Download an archive of your data**
2. Tunggu email, unduh dan ekstrak zip-nya
3. Taruh folder hasil ekstrak sebagai `XArchive/` di root proyek:

```
XPostDeleter/
  XArchive/
    data/
      tweets.js
      tweets_media/
        12345678-photo.jpg
        ...
```

---

### Langkah 2 — Buat daftar hapus

#### Pindai gambar / video saja (default)

Mendeteksi postingan yang mengandung wajahmu atau konten NSFW:

```bash
python archive_scanner.py
```

> Jika `delete_hit_list.csv` sudah ada, analisis gambar/video otomatis dilewati — hanya tweet baru yang diproses.

#### Gambar + analisis teks

Juga memindai seluruh teks tweet dengan pencocokan keyword dan penilaian LLM:

```bash
python archive_scanner.py --text
```

**Pipeline analisis teks (`--text`):**

| Tahap | Engine | Kapan digunakan |
|-------|--------|-----------------|
| 1 — Keyword | `keywords.json` lokal | selalu (instan, gratis) |
| 2 — Gemini | Gemini API (tier gratis) | tweet yang lolos filter keyword |
| 3 — Claude | Claude API (opsional) | tweet yang dinilai meragukan oleh Gemini |

> Tier gratis Gemini (15 RPM) sudah cukup. Arsip 10.000 tweet membutuhkan sekitar 30 menit untuk analisis teks.

Ini akan membuat (atau memperbarui) `delete_hit_list.csv`:

| Kolom | Keterangan |
|-------|------------|
| `created_at` | Waktu postingan |
| `delete_url` | URL postingan |
| `severity` | Skor risiko 0–5 |
| `risk_tags` | misal `FACE_SELFIE`, `NSFW_HIGH`, `TEXT_KEYWORD`, `TEXT_GEMINI` |
| `full_text` | Teks postingan |
| `hapus` | Status penghapusan (kosong = belum, `sudah` = selesai) |

**Selalu tinjau CSV dan hapus baris yang ingin kamu pertahankan sebelum melanjutkan.**

---

### Langkah 3 — Jalankan agen penghapus

#### Opsi A — Menempel ke Chrome yang sudah berjalan

1. Tutup semua jendela Chrome, lalu jalankan Chrome dengan remote debugging:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:USER_DATA_DIR" `
  --profile-directory="Default"
```

2. Login ke X secara manual di jendela Chrome tersebut.

3. Jalankan agennya:

```bash
python delete_agent.py --attach-existing --limit 50
```

#### Opsi B — Biarkan Selenium menjalankan Chrome secara otomatis

```bash
python delete_agent.py --limit 50
```

#### Opsi-opsi utama

| Opsi | Default | Keterangan |
|------|---------|------------|
| `--limit N` | 50 | Maksimal postingan yang dihapus per run |
| `--allow-low-severity` | mati | Juga hapus postingan severity < 1 |
| `--attach-existing` | mati | Menempel ke Chrome yang berjalan di port 9222 |
| `--rt` | mati | Proses `rt_hit_list.csv` (mode batalkan repost) |
| `--log-file PATH` | `xpostdeleter.log` | Path file log |
| `--debug-rt` | mati | Log deteksi RT/repost yang lebih detail |

---

### Struktur proyek

```
XPostDeleter/
  delete_agent.py        # Entry point (CLI)
  actions.py             # Rutinitas hapus / batalkan repost
  browser.py             # Factory ChromeDriver & navigasi
  human.py               # Mouse, scroll, timing seperti manusia
  utils.py               # Logging tee & progress bar
  archive_scanner.py     # Pindai arsip → delete_hit_list.csv
  image_analyzer.py      # Pengenalan wajah & deteksi NSFW
  text_analyzer.py       # Analisis teks 3 tahap (keyword / Gemini / Claude)
  keywords.json.example  # Template daftar keyword (salin ke keywords.json)
  .env.example           # Template variabel lingkungan
  requirements.txt       # Dependensi Python
```

### Disclaimer

> **Baca dengan seksama sebelum digunakan.**

- Alat ini hanya untuk **penggunaan pribadi** — menghapus postingan milikmu sendiri.
- Interaksi browser otomatis mungkin melanggar Ketentuan Layanan X — **gunakan dengan risiko sendiri**.
- Saat dijalankan, **jangan sentuh mouse** (pyautogui mengontrolnya).
- Jaga ukuran batch tetap wajar (20–50 per run) untuk mengurangi risiko deteksi.
- **Deteksi AI (gambar, NSFW, dan teks) tidak sempurna.** False positive akan terjadi — postingan yang sama sekali tidak terkait dengan target yang kamu maksud bisa saja masuk ke daftar hapus. **Selalu tinjau `delete_hit_list.csv` sebelum menjalankan agen penghapus.** Penulis tidak bertanggung jawab atas postingan yang terhapus akibat false positive atau kesalahan deteksi.
