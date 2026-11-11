import asyncio
import os
import shutil
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def download_video(
    url: str, temp_dir: str, max_size_mb: int, cookies_file: str | None = None
) -> str | None:
    """Download a short video (TikTok, Reels, Shorts). Returns the file path on success, None on failure."""
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4()
    output_path = os.path.join(temp_dir, f"{job_id}.mp4")

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--quiet",
        "--format", "bv*+ba/b",
        # H.264 + AAC plays inline in every Telegram client; cap at 1080p to stay under the size limit.
        "--format-sort", "vcodec:h264,res:1080,acodec:m4a",
        "--merge-output-format", "mp4",
        "--max-filesize", f"{max_size_mb}M",
        "--no-playlist",
        "--extractor-retries", "3",
        "--socket-timeout", "30",
        "--output", output_path,
    ]

    cookies_copy = None
    if cookies_file and os.path.isfile(cookies_file):
        # yt-dlp writes cookies back on exit, so hand it a copy: a read-only mount would make it fail.
        cookies_copy = os.path.join(temp_dir, f"{job_id}.cookies.txt")
        shutil.copyfile(cookies_file, cookies_copy)
        cmd += ["--cookies", cookies_copy]
    cmd.append(url)

    logger.info("Downloading video: %s", url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    finally:
        if cookies_copy and os.path.exists(cookies_copy):
            os.remove(cookies_copy)

    if proc.returncode != 0:
        logger.error("yt-dlp failed (rc=%d): %s", proc.returncode, stderr.decode())
        return None

    if not os.path.exists(output_path):
        logger.error("No file downloaded (too large or unavailable): %s", url)
        return None

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if size_mb > max_size_mb:
        logger.warning("Video too large: %.1f MB (limit %d MB)", size_mb, max_size_mb)
        os.remove(output_path)
        return None

    logger.info("Downloaded %.1f MB to %s", size_mb, output_path)
    return output_path
