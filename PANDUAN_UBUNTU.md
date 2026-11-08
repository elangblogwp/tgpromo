# Instalasi pada VPS Ubuntu tanpa domain

Panduan ini menggunakan IP publik VPS, Docker Compose, dan HTTPS dari Let's Encrypt. Contoh alamat panel: `https://IP_PUBLIK_VPS`. Tidak perlu membeli domain atau mengatur DNS. Python, Telethon, dan Caddy berjalan di container.

Disarankan Ubuntu Server 24.04 LTS 64-bit. Jalankan perintah melalui SSH dengan akun yang memiliki akses `sudo`. Jika memakai root, perintah `sudo` tetap dapat digunakan apabila paket sudo tersedia.

## 1. Siapkan IP publik dan akses Telegram

Siapkan IP publik IPv4 yang ditetapkan provider kepada VPS. Pakai IP yang stabil. Alamat `203.0.113.10` dalam contoh adalah alamat dokumentasi, bukan IP yang bisa digunakan untuk instalasi nyata.

Untuk sertifikat IP, VPS harus dapat menerima koneksi publik pada TCP 80 dan 443. Pertahankan port SSH yang sedang dipakai. Port 8080 tidak perlu dibuka. UDP 443 bersifat opsional.

Buat bot melalui [@BotFather](https://t.me/BotFather) dengan `/newbot` dan simpan tokennya. Dapatkan `API_ID` serta `API_HASH` melalui [my.telegram.org/apps](https://my.telegram.org/apps). Token BotFather dan API ID/hash diperlukan untuk fungsi yang berbeda.

Untuk langkah di bawah, bot harus baru dan belum dipakai aplikasi lain. Jangan membagikan token, API hash, password 2FA, atau `.env` ke percakapan publik.

## 2. Perbarui Ubuntu

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl unzip nano
```

Jika pembaruan meminta reboot, lakukan reboot dan masuk SSH lagi sebelum melanjutkan.

## 3. Pasang Docker Engine dan Compose

Tambahkan repository resmi Docker:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
```

Panduan ini untuk Ubuntu fresh yang belum memiliki Docker dari sumber lain. Repository resmi Docker mencantumkan paket lama yang perlu dilepas apabila server ternyata sudah memiliki instalasi Docker lain.

## 4. Pastikan port tersedia

Di panel provider VPS, izinkan inbound TCP 80 dan 443 ke VPS ini. Pastikan tidak ada Nginx, Apache, atau layanan lain yang memakai kedua port tersebut. Jangan hentikan layanan lain tanpa memastikan fungsinya terlebih dahulu.

Jika UFW sudah aktif pada VPS, tambahkan:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

Tidak perlu mengaktifkan atau mereset UFW untuk mengikuti panduan ini. Aturan firewall provider tetap perlu benar. Docker dapat melewati sebagian aturan UFW untuk port container yang dipublikasikan; paket ini hanya mempublikasikan port Caddy, bukan port Python 8080.

## 5. Unggah dan ekstrak paket terbaru

Unduh `telegram-userbot.zip` versi terbaru dari percakapan ini. Unggah ke direktori home akun SSH melalui SFTP. Dari HP, gunakan fitur SFTP pada aplikasi SSH yang mendukungnya.

Jika menggunakan komputer, perintah berikut dijalankan di komputer, bukan di VPS. Ganti `USER` dan `IP_VPS`:

```bash
scp telegram-userbot.zip USER@IP_VPS:~/
```

Kemudian pada terminal VPS:

```bash
mkdir -p "$HOME/apps"
unzip "$HOME/telegram-userbot.zip" -d "$HOME/apps"
cd "$HOME/apps/telegram-userbot"
test -f .env || cp .env.example .env
chmod 600 .env
```

Semua perintah `docker compose` selanjutnya dijalankan dari direktori ini.

## 6. Bangun aplikasi dan buat kunci sesi

```bash
sudo docker compose build userbot
sudo docker compose run --rm --no-deps userbot python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Salin hasil perintah kedua untuk `SESSION_KEY`. Buat kunci ini sekali untuk instalasi tersebut dan simpan dengan aman. Kunci yang sama diperlukan agar sesi tersimpan tetap dapat dibuka setelah restart.

## 7. Isi konfigurasi

```bash
nano .env
```

Isi nilai berikut dengan data milikmu:

```dotenv
API_ID=123456
API_HASH=isi_api_hash_32_karakter
BOT_TOKEN=isi_token_botfather
OWNER_ID=isi_id_telegram_numerik
SESSION_KEY=isi_kunci_dari_langkah_6
PUBLIC_IP=203.0.113.10
PUBLIC_BASE_URL=https://203.0.113.10
```

Ganti IP pada kedua baris terakhir dengan IP publik VPS yang sebenarnya. `PUBLIC_IP` hanya berisi IP, sedangkan `PUBLIC_BASE_URL` diawali `https://` dan menggunakan IP yang sama. Jangan menambahkan `/login`, port 8080, atau path lain. Biarkan pengaturan lain dari template tetap ada.

Simpan di nano dengan `Ctrl+O`, `Enter`, lalu keluar dengan `Ctrl+X`. Jika belum tahu `OWNER_ID`, selesaikan langkah berikut sebelum menjalankan layanan utama. Nilai sementara dalam file belum digunakan untuk memberi akses selama layanan utama belum dimulai.

## 8. Ambil OWNER_ID dari bot sendiri

Langkah ini bisa dilewati jika kamu sudah tahu ID Telegram akunmu.

Buka bot yang baru dibuat dan kirim `/start` dari akun yang akan menjadi owner. Bot belum membalas karena layanan belum dijalankan; pesan itu tetap dapat dibaca lewat Bot API.

Pada VPS, jalankan:

```bash
sudo docker compose run --rm --no-deps userbot python -m userbot.account_id
```

Contoh hasil:

```json
{"id": 123456789, "username": "username_kamu", "name": "Nama Kamu"}
```

Gunakan angka `id` untuk akunmu, bukan ID bot dan bukan ID grup. Jika lebih dari satu akun muncul, pilih akunmu sendiri berdasarkan username/nama. Perintah ini tidak memberikan izin kepada siapa pun.

Buka `.env` kembali dan isi `OWNER_ID`:

```bash
nano .env
```

Jika hasil kosong, kirim `/start` lagi lalu ulangi. Jika gagal, periksa `BOT_TOKEN`, koneksi ke Telegram, dan bahwa bot ini belum dipasangi webhook atau digunakan aplikasi lain.

## 9. Jalankan bot dan HTTPS

```bash
sudo docker compose pull caddy
sudo docker compose config --quiet
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 userbot caddy
```

Caddy meminta sertifikat IP publik melalui Let's Encrypt menggunakan profil `shortlived`. Tidak diperlukan Certbot, domain, atau perubahan DNS. Sertifikat IP berlaku sekitar enam hari dan diperbarui otomatis oleh Caddy; biarkan layanan berjalan serta port validasi tetap dapat diakses.

Buka `https://IP_PUBLIK_VPS` melalui browser HP atau komputer. Halaman tanpa token akan meminta kamu memulai login dari bot. Itu normal.

Pastikan tidak ada peringatan sertifikat pada browser sebelum mengisi kode atau password. Jika belum berhasil, periksa log Caddy, IP konfigurasi, firewall provider, TCP 80/443, dan waktu sistem VPS. Jangan mengabaikan peringatan sertifikat untuk melanjutkan autentikasi.

## 10. Login dan kelola pengguna

Buka bot milikmu dan kirim:

```text
/start
```

Owner sudah otomatis mendapat akses. Untuk memberi akses ke akun lain:

```text
/adduser 123456789
```

Ganti angka itu dengan ID akun pengguna yang benar. Pengguna bisa mengirim `/id` ke bot untuk melihat ID-nya setelah layanan berjalan.

Untuk menghubungkan akunmu, kirim nomor dengan kode negara:

```text
/login +6281234567890
```

Tekan **Connect my Telegram account**, lalu **Send verification code**. Masukkan kode Telegram dan password 2FA pada halaman HTTPS di IP VPS tersebut. Jangan kirim kode atau password ke chat bot. Akun yang dihubungkan harus akun yang sama dengan pengirim `/login`.

Tautan login hanya bisa dibuka sekali dan memiliki masa berlaku. Jika halaman terlanjur dimuat ulang atau kedaluwarsa, kirim `/login` lagi untuk memperoleh tautan baru.

## 11. Aktifkan balasan di grup diskusi

Bergabunglah secara manual ke channel dan grup diskusi yang ingin digunakan. Pilih grup yang mengizinkan promosi.

Buka **Saved Messages / Pesan Tersimpan** pada akun yang sudah login. Kirim perintah berikut satu per satu sebagai pesan terpisah:

```text
.keyword noktel, netflix, spotify
.text Ready stock, DM me!|Fast response, contact me!|Cheap prices available, PM me!
.listgc
```

Dari hasil `.listgc`, salin ID grup diskusi yang benar. Kemudian kirim satu per satu:

```text
.watch -1001234567890
.on
.status
```

Ganti ID contoh dengan ID grupmu. Gunakan `.help` untuk seluruh perintah dan `.off` untuk menghentikan balasan otomatis.

Batas default adalah jeda minimum 60 detik antara percobaan kirim dan maksimal 6 percobaan balasan per jam per akun. Post yang melewati batas dilewati, bukan ditumpuk untuk dikirim nanti. Nilai ini bisa diubah melalui `.env`; batas dan pembatasan Telegram tetap berlaku.

Uji dahulu pada channel dan grup diskusi milikmu: satu post asli dengan kata kunci harus mendapat balasan dalam thread yang tepat; komentar pengguna dengan kata kunci dan post tanpa kata kunci harus diabaikan.

## 12. Perintah pemeliharaan

Melihat log langsung:

```bash
cd "$HOME/apps/telegram-userbot"
sudo docker compose logs -f --tail=100
```

Tekan `Ctrl+C` untuk keluar dari tampilan log; bot tetap berjalan.

Memulai ulang layanan dengan konfigurasi yang sama:

```bash
sudo docker compose restart
```

Setelah mengubah `.env`, buat ulang container agar lingkungan baru terbaca:

```bash
sudo docker compose up -d --force-recreate
```

Menghentikan layanan sementara:

```bash
sudo docker compose stop
```

Menjalankan kembali:

```bash
sudo docker compose up -d
```

Docker dimulai otomatis saat boot, dan container memakai `restart: unless-stopped`. Container yang sengaja dihentikan akan tetap berhenti sampai dijalankan kembali. Sesi, pengaturan, sertifikat, dan riwayat duplikasi berada dalam named volume. Pertahankan volume dan `SESSION_KEY`; jangan menghapusnya saat upgrade biasa.

## Status verifikasi

Paket memiliki 93 tes otomatis yang lulus. Konfigurasi Caddy diperiksa dengan Caddy 2.11.8 untuk issuer ACME produksi, profil `shortlived`, dan pemilihan sertifikat IP ketika SNI tidak dikirim. Penerbitan sertifikat untuk IP VPS milikmu dan login Telegram nyata baru dapat diuji setelah kamu memasangnya. Probabilitas akun dibatasi atau diblokir Telegram tidak dapat dijamin oleh aplikasi.

## Referensi

- [Instalasi Docker resmi untuk Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Sertifikat IP dan profil shortlived dari Let's Encrypt](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)
- [Pengaturan TLS Caddy](https://caddyserver.com/docs/caddyfile/directives/tls)
- [Dukungan Caddy untuk sertifikat IP publik](https://github.com/caddyserver/caddy/issues/7118)
- [Telegram Bot API](https://core.telegram.org/bots/api)
