import os

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
TEMP_DIR: str = os.getenv("TEMP_DIR", "/tmp/tiktok")
