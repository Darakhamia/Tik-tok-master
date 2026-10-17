import os

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
TEMP_DIR: str = os.getenv("TEMP_DIR", "/tmp/tiktok")

# Thread ID of the "TikTok" topic: in groups with topics every video is posted there.
_topic_id = os.getenv("TIKTOK_TOPIC_ID", "").strip()
TIKTOK_TOPIC_ID: int | None = int(_topic_id) if _topic_id else None
