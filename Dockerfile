FROM python:3.11-slim

# Install ffmpeg (required by yt-dlp for stream merging)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash botuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py downloader.py config.py healthcheck.py ./

# Temp directory owned by botuser
RUN mkdir -p /tmp/tiktok && chown botuser:botuser /tmp/tiktok

USER botuser

HEALTHCHECK NONE

CMD ["python", "bot.py"]
