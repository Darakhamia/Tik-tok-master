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

COPY bot.py downloader.py config.py storage.py healthcheck.py ./

# Temp and data directories owned by botuser
RUN mkdir -p /tmp/tiktok /app/data && chown botuser:botuser /tmp/tiktok /app/data

USER botuser

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 CMD ["python", "/app/healthcheck.py"]

CMD ["python", "bot.py"]
