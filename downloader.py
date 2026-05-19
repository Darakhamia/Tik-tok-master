import asyncio
import os
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def download_tiktok(url: str, temp_dir: str, max_size_mb: int) -> str | None:
    """Download a TikTok video. Returns the file path on success, None on failure."""
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    output_path = os.path.join(temp_dir, f"{uuid.uuid4()}.mp4")

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--quiet",
        "--format", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--extractor-retries", "3",
        "--socket-timeout", "30",
        "--output", output_path,
        url,
    ]

    logger.info("Downloading TikTok video: %s", url)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error("yt-dlp failed (rc=%d): %s", proc.returncode, stderr.decode())
        return None

    if not os.path.exists(output_path):
        logger.error("yt-dlp exited cleanly but output file not found: %s", output_path)
        return None

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if size_mb > max_size_mb:
        logger.warning("Video too large: %.1f MB (limit %d MB)", size_mb, max_size_mb)
        os.remove(output_path)
        return None

    logger.info("Downloaded %.1f MB to %s", size_mb, output_path)
    return output_path
