#!/usr/bin/env bash
# Arch Linux セットアップスクリプト
# root で実行: sudo bash setup.sh
set -euo pipefail

INSTALL_DIR="/opt/vrc-lt"
BOT_USER="vrc-lt"

echo "=== 依存パッケージのインストール ==="
pacman -Sy --noconfirm python ffmpeg poppler

echo "=== ユーザー・ディレクトリ作成 ==="
useradd -r -s /usr/bin/nologin "$BOT_USER" 2>/dev/null || true
mkdir -p "$INSTALL_DIR"

echo "=== ファイルのコピー ==="
cp bot.py requirements.txt "$INSTALL_DIR/"
cp .env.example "$INSTALL_DIR/.env"
echo ">>> $INSTALL_DIR/.env を編集してください"

echo "=== Python仮想環境のセットアップ ==="
python -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "=== 権限設定 ==="
chown -R "$BOT_USER":"$BOT_USER" "$INSTALL_DIR"

echo "=== systemd サービスの登録 ==="
cp systemd/vrc-lt-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable vrc-lt-bot

echo ""
echo "=== セットアップ完了 ==="
echo "1. $INSTALL_DIR/.env を編集してください"
echo "2. systemctl start vrc-lt-bot でbot起動"
echo "3. journalctl -u vrc-lt-bot -f でログ確認"
