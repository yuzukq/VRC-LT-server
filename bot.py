import asyncio
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import boto3
import discord
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "50"))

# Cloudflare R2
R2_ACCOUNT_ID = os.environ["R2_ACCOUNT_ID"]
R2_ACCESS_KEY_ID = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_BUCKET_NAME = os.environ["R2_BUCKET_NAME"]
R2_PUBLIC_URL = os.environ["R2_PUBLIC_URL"].rstrip("/")  # e.g. https://pub-xxx.r2.dev

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(signature_version="s3v4"),
)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def convert_and_upload(pdf_path: Path, object_key: str) -> tuple[bool, str, int]:
    """PDFをMP4に変換してR2にアップロードする。(成功, エラーメッセージ, スライド枚数) を返す"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        img_prefix = tmp / "slide"

        # PDF → PNG画像列 (150dpi)
        result = subprocess.run(
            ["pdftoppm", "-png", "-r", "150", str(pdf_path), str(img_prefix)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return False, f"pdftoppm失敗:\n```{result.stderr[:500]}```", 0

        images = sorted(tmp.glob("slide-*.png"))
        if not images:
            return False, "スライド画像の生成に失敗しました", 0

        # ffmpeg concat用ファイルリスト (各スライド1秒表示)
        concat_file = tmp / "concat.txt"
        with open(concat_file, "w") as f:
            for img in images:
                f.write(f"file '{img}'\n")
                f.write("duration 1\n")
            # concat demuxerのバグ回避: 最後のフレームを再度追加
            f.write(f"file '{images[-1]}'\n")

        mp4_path = tmp / "output.mp4"

        # PDF → MP4
        # - scale: 1920x1080にfit (アスペクト比維持、余白は黒)
        # - libx264 + yuv420p: 幅広い互換性
        # - movflags faststart: moovアトムを先頭に (シーク対応)
        result = subprocess.run(
            [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                       "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
                "-c:v", "libx264",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-y",
                str(mp4_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return False, f"ffmpeg失敗:\n```{result.stderr[-500:]}```", 0

        # R2へアップロード
        s3.upload_file(
            str(mp4_path),
            R2_BUCKET_NAME,
            object_key,
            ExtraArgs={"ContentType": "video/mp4"},
        )

    return True, "", len(images)


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (id: {client.user.id})")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id != CHANNEL_ID:
        return

    pdf_attachment = next(
        (a for a in message.attachments if a.filename.lower().endswith(".pdf")),
        None,
    )
    if pdf_attachment is None:
        return

    if pdf_attachment.size > MAX_FILE_MB * 1024 * 1024:
        await message.reply(f"ファイルサイズが大きすぎます (上限: {MAX_FILE_MB}MB)")
        return

    status_msg = await message.reply(
        f"`{pdf_attachment.filename}` を受け取りました。変換中..."
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "input.pdf"
        await pdf_attachment.save(pdf_path)

        video_id = uuid.uuid4().hex[:10]
        safe_name = "".join(c for c in message.author.display_name if c.isascii() and c.isalnum())[:20] or "user"
        filename = f"{safe_name}_{video_id}.mp4"
        object_key = f"videos/{filename}"

        loop = asyncio.get_event_loop()
        ok, err_msg, slide_count = await loop.run_in_executor(
            None, convert_and_upload, pdf_path, object_key
        )

    if not ok:
        await status_msg.edit(content=f"変換に失敗しました。{err_msg}")
        return

    url = f"{R2_PUBLIC_URL}/{object_key}"
    await status_msg.edit(
        content=(
            f"変換完了！\n"
            f"スライド枚数: **{slide_count}枚**\n"
            f"URL: {url}"
        )
    )


client.run(TOKEN)
