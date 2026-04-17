#!/usr/bin/env bash
# Arch Linux セットアップスクリプト
# root で実行: sudo bash setup.sh
set -euo pipefail

DOMAIN="${1:-lt.example.com}"  # 引数でドメインを指定: sudo bash setup.sh lt.yourdomain.com
INSTALL_DIR="/opt/vrc-lt"
BOT_USER="vrc-lt"

echo "=== 依存パッケージのインストール ==="
pacman -Sy --noconfirm \
    nginx \
    python \
    python-pip \
    ffmpeg \
    poppler \          # pdftoppm が含まれる
    certbot \
    certbot-nginx

echo "=== ユーザー・ディレクトリ作成 ==="
useradd -r -s /usr/bin/nologin "$BOT_USER" 2>/dev/null || true
mkdir -p "$INSTALL_DIR/videos"
mkdir -p /var/www/certbot

echo "=== ファイルのコピー ==="
cp bot.py requirements.txt "$INSTALL_DIR/"
cp .env.example "$INSTALL_DIR/.env"
echo ">>> $INSTALL_DIR/.env を編集してください (DISCORD_TOKEN, CHANNEL_ID, BASE_URL)"

echo "=== Python仮想環境のセットアップ ==="
python -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "=== nginx設定 ==="
# sites-enabled ディレクトリがなければ作成
mkdir -p /etc/nginx/sites-{available,enabled}
# nginx.conf に include を追加 (まだなければ)
grep -q "sites-enabled" /etc/nginx/nginx.conf || \
    sed -i '/http {/a\    include /etc/nginx/sites-enabled/*;' /etc/nginx/nginx.conf

sed "s/lt\.example\.com/$DOMAIN/g" nginx/vrc-lt.conf \
    > "/etc/nginx/sites-available/vrc-lt.conf"
ln -sf /etc/nginx/sites-available/vrc-lt.conf /etc/nginx/sites-enabled/

# まず HTTP のみで起動して certbot を実行
sed -i '/ssl_/d;/https/d' /etc/nginx/sites-available/vrc-lt.conf || true
nginx -t && systemctl enable --now nginx

echo "=== Let's Encrypt 証明書の取得 ==="
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "your@email.com"
# → 成功したら nginx.conf に ssl の設定が自動追記される
# → その後 nginx/vrc-lt.conf の内容を再適用して mp4 ブロックを追加する

echo "=== VIDEO_DIR の権限設定 ==="
chown -R "$BOT_USER":"$BOT_USER" "$INSTALL_DIR/videos"
# nginxもvideos以下を読める必要がある
chmod 755 "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR/videos"

echo "=== systemd サービスの登録 ==="
sed "s|/opt/vrc-lt|$INSTALL_DIR|g" systemd/vrc-lt-bot.service \
    > /etc/systemd/system/vrc-lt-bot.service
systemctl daemon-reload
systemctl enable vrc-lt-bot

echo ""
echo "=== セットアップ完了 ==="
echo "1. $INSTALL_DIR/.env を編集してください"
echo "2. systemctl start vrc-lt-bot でbot起動"
echo "3. journalctl -u vrc-lt-bot -f でログ確認"
