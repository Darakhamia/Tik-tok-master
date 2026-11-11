import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS reactions (
                chat_id INTEGER, message_id INTEGER, user_id INTEGER, kind TEXT,
                PRIMARY KEY (chat_id, message_id, user_id, kind)
            );
            CREATE TABLE IF NOT EXISTS topics (
                chat_id INTEGER PRIMARY KEY, thread_id INTEGER
            );
            """
        )
        self._db.commit()

    def has_reaction(self, chat_id: int, message_id: int, user_id: int, kind: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM reactions WHERE chat_id=? AND message_id=? AND user_id=? AND kind=?",
            (chat_id, message_id, user_id, kind),
        ).fetchone()
        return row is not None

    def add_reaction(self, chat_id: int, message_id: int, user_id: int, kind: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO reactions VALUES (?, ?, ?, ?)",
            (chat_id, message_id, user_id, kind),
        )
        self._db.commit()

    def remove_reaction(self, chat_id: int, message_id: int, user_id: int, kind: str) -> None:
        self._db.execute(
            "DELETE FROM reactions WHERE chat_id=? AND message_id=? AND user_id=? AND kind=?",
            (chat_id, message_id, user_id, kind),
        )
        self._db.commit()

    def counts(self, chat_id: int, message_id: int) -> dict[str, int]:
        rows = self._db.execute(
            "SELECT kind, COUNT(*) FROM reactions WHERE chat_id=? AND message_id=? GROUP BY kind",
            (chat_id, message_id),
        ).fetchall()
        return dict(rows)

    def get_topic(self, chat_id: int) -> int | None:
        row = self._db.execute("SELECT thread_id FROM topics WHERE chat_id=?", (chat_id,)).fetchone()
        return row[0] if row else None

    def set_topic(self, chat_id: int, thread_id: int) -> None:
        self._db.execute("INSERT OR REPLACE INTO topics VALUES (?, ?)", (chat_id, thread_id))
        self._db.commit()
