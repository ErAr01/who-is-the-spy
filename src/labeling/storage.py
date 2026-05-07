import hashlib
import io
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from src.labeling.models import CardRecord, CardTags


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, object]) -> None:
    payload = {
        "sessionId": "236bbb",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    log_paths = (
        Path("/Users/artemermilov/PycharmProjects/who_is_the_spy/.cursor/debug-236bbb.log"),
        Path("/app/.cursor/debug-236bbb.log"),
    )
    for log_path in log_paths:
        try:
            # region agent log
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as debug_file:
                debug_file.write(json.dumps(payload, ensure_ascii=True) + "\n")
            # endregion
            break
        except OSError:
            continue


class LabelingStorage:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cards (
                    id                 TEXT PRIMARY KEY,
                    name               TEXT NOT NULL,
                    wiki_url           TEXT,
                    image_bytes        BLOB NOT NULL,
                    image_mime         TEXT NOT NULL,
                    thumbnail_bytes    BLOB NOT NULL,
                    image_sha256       TEXT NOT NULL UNIQUE,
                    tags_json          TEXT NOT NULL,
                    appearance_text    TEXT NOT NULL,
                    embedding          BLOB NOT NULL,
                    embedding_model    TEXT NOT NULL,
                    vision_model       TEXT NOT NULL,
                    labeled_at         TEXT NOT NULL,
                    notes              TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS card_tags (
                    card_id   TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                    category  TEXT NOT NULL,
                    value     TEXT NOT NULL,
                    PRIMARY KEY (card_id, category, value)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_card_tags_value ON card_tags(category, value)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pair_history (
                    used_at  TEXT NOT NULL,
                    card_a   TEXT NOT NULL,
                    card_b   TEXT NOT NULL,
                    chat_id  INTEGER
                )
                """
            )
            self._ensure_pair_history_chat_scope(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pair_history_recent ON pair_history(used_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pair_history_chat_recent ON pair_history(chat_id, used_at)")
            conn.commit()

    def normalize_image(self, image_bytes: bytes) -> tuple[bytes, bytes, str]:
        with Image.open(io.BytesIO(image_bytes)) as image:
            normalized = image.convert("RGB")
            normalized.thumbnail((1024, 1024))

            full_buffer = io.BytesIO()
            normalized.save(full_buffer, format="JPEG", quality=88, optimize=True)
            full_bytes = full_buffer.getvalue()

            thumb = normalized.copy()
            thumb.thumbnail((256, 256))
            thumb_buffer = io.BytesIO()
            thumb.save(thumb_buffer, format="JPEG", quality=80, optimize=True)
            thumb_bytes = thumb_buffer.getvalue()

        return full_bytes, thumb_bytes, "image/jpeg"

    @staticmethod
    def sha256_digest(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def find_card_by_sha256(self, image_sha256: str) -> CardRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cards WHERE image_sha256 = ?", (image_sha256,)).fetchone()
        if row is None:
            return None
        return self._row_to_card(row)

    def save_card(
        self,
        card_id: str,
        name: str,
        wiki_url: str | None,
        image_bytes: bytes,
        image_mime: str,
        thumbnail_bytes: bytes,
        image_sha256: str,
        tags: CardTags,
        appearance_text: str,
        embedding: np.ndarray,
        embedding_model: str,
        vision_model: str,
        dataset_categories: list[str] | None = None,
        notes: str | None = None,
    ) -> CardRecord:
        labeled_at = datetime.now(UTC).isoformat()
        tags_json = tags.model_dump_json()
        embedding_blob = self._embedding_to_blob(embedding)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cards (
                    id, name, wiki_url, image_bytes, image_mime, thumbnail_bytes, image_sha256,
                    tags_json, appearance_text, embedding, embedding_model, vision_model, labeled_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    wiki_url=excluded.wiki_url,
                    image_bytes=excluded.image_bytes,
                    image_mime=excluded.image_mime,
                    thumbnail_bytes=excluded.thumbnail_bytes,
                    image_sha256=excluded.image_sha256,
                    tags_json=excluded.tags_json,
                    appearance_text=excluded.appearance_text,
                    embedding=excluded.embedding,
                    embedding_model=excluded.embedding_model,
                    vision_model=excluded.vision_model,
                    labeled_at=excluded.labeled_at,
                    notes=excluded.notes
                """,
                (
                    card_id,
                    name,
                    wiki_url,
                    image_bytes,
                    image_mime,
                    thumbnail_bytes,
                    image_sha256,
                    tags_json,
                    appearance_text,
                    embedding_blob,
                    embedding_model,
                    vision_model,
                    labeled_at,
                    notes,
                ),
            )
            conn.execute("DELETE FROM card_tags WHERE card_id = ?", (card_id,))
            conn.executemany(
                "INSERT INTO card_tags (card_id, category, value) VALUES (?, ?, ?)",
                self._build_tag_rows(card_id, tags, dataset_categories),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return self._row_to_card(row)

    def get_card(self, card_id: str) -> CardRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_card(row)

    def list_cards(self) -> list[CardRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM cards ORDER BY labeled_at DESC").fetchall()
        return [self._row_to_card(row) for row in rows]

    def list_dataset_categories(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT value
                FROM card_tags
                WHERE category = 'dataset_category'
                ORDER BY value ASC
                """
            ).fetchall()
        return [str(row["value"]) for row in rows]

    def list_cards_by_dataset_categories(self, categories: list[str] | None = None) -> list[CardRecord]:
        normalized = self._normalize_categories(categories)
        with self._connect() as conn:
            if normalized:
                placeholders = ", ".join("?" for _ in normalized)
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT c.*
                    FROM cards c
                    INNER JOIN card_tags t ON t.card_id = c.id
                    WHERE t.category = 'dataset_category' AND t.value IN ({placeholders})
                    ORDER BY c.labeled_at DESC
                    """,
                    tuple(normalized),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM cards ORDER BY labeled_at DESC").fetchall()
        return [self._row_to_card(row) for row in rows]

    def get_dataset_categories(self, card_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT value
                FROM card_tags
                WHERE card_id = ? AND category = 'dataset_category'
                ORDER BY value ASC
                """,
                (card_id,),
            ).fetchall()
        return [str(row["value"]) for row in rows]

    def get_image_bytes(self, card_id: str, thumbnail: bool = False) -> bytes | None:
        column = "thumbnail_bytes" if thumbnail else "image_bytes"
        with self._connect() as conn:
            row = conn.execute(f"SELECT {column} FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return None
        return bytes(row[0])

    def load_all_embeddings(self) -> list[tuple[str, np.ndarray]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, embedding FROM cards").fetchall()
        return [(row["id"], self._blob_to_embedding(row["embedding"])) for row in rows]

    def get_embedding(self, card_id: str) -> np.ndarray | None:
        with self._connect() as conn:
            row = conn.execute("SELECT embedding FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return None
        return self._blob_to_embedding(row["embedding"])

    def add_pair_history(
        self,
        card_a: str,
        card_b: str,
        *,
        chat_id: int | None = None,
        used_at: datetime | None = None,
    ) -> None:
        left, right = self._normalize_pair(card_a, card_b)
        ts = (used_at or datetime.now(UTC)).astimezone(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pair_history (used_at, card_a, card_b, chat_id) VALUES (?, ?, ?, ?)",
                (ts, left, right, chat_id),
            )
            conn.commit()

    def get_recent_pair_set(
        self,
        limit: int | None,
        *,
        chat_id: int | None = None,
        since: datetime | None = None,
    ) -> set[tuple[str, str]]:
        sql = "SELECT card_a, card_b FROM pair_history"
        params: list[object] = []
        where_parts: list[str] = []
        if chat_id is not None:
            where_parts.append("chat_id = ?")
            params.append(chat_id)
        if since is not None:
            where_parts.append("used_at >= ?")
            params.append(since.astimezone(UTC).isoformat())
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        sql += " ORDER BY used_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        result: set[tuple[str, str]] = set()
        for row in rows:
            result.add(self._normalize_pair(row["card_a"], row["card_b"]))
        return result

    def get_recent_seed_counts(self, limit: int, *, chat_id: int | None = None) -> dict[str, int]:
        where_clause = "WHERE chat_id = ?" if chat_id is not None else ""
        params: tuple[object, ...] = (chat_id, limit, chat_id, limit) if chat_id is not None else (limit, limit)
        sql = """
                SELECT card_id, COUNT(*) AS cnt
                FROM (
                    SELECT card_id
                    FROM (
                        SELECT card_a AS card_id
                        FROM pair_history
                        {where_clause}
                        ORDER BY used_at DESC
                        LIMIT ?
                    )
                    UNION ALL
                    SELECT card_id
                    FROM (
                        SELECT card_b AS card_id
                        FROM pair_history
                        {where_clause}
                        ORDER BY used_at DESC
                        LIMIT ?
                    )
                )
                GROUP BY card_id
                """.format(where_clause=where_clause)
        # region agent log
        _debug_log(
            run_id="pre-fix",
            hypothesis_id="H1",
            location="src/labeling/storage.py:get_recent_seed_counts:entry",
            message="get_recent_seed_counts entry",
            data={"limit": limit, "chat_id": chat_id, "where_clause": where_clause, "params": list(params)},
        )
        # endregion
        # region agent log
        _debug_log(
            run_id="pre-fix",
            hypothesis_id="H2",
            location="src/labeling/storage.py:get_recent_seed_counts:sql",
            message="built SQL for get_recent_seed_counts",
            data={"sql": " ".join(sql.split())},
        )
        # endregion
        with self._connect() as conn:
            # region agent log
            _debug_log(
                run_id="pre-fix",
                hypothesis_id="H3",
                location="src/labeling/storage.py:get_recent_seed_counts:sqlite",
                message="sqlite runtime info",
                data={"sqlite_version": sqlite3.sqlite_version},
            )
            # endregion
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                # region agent log
                _debug_log(
                    run_id="pre-fix",
                    hypothesis_id="H4",
                    location="src/labeling/storage.py:get_recent_seed_counts:exception",
                    message="OperationalError during get_recent_seed_counts",
                    data={"error": str(exc)},
                )
                # endregion
                raise
            # region agent log
            _debug_log(
                run_id="pre-fix",
                hypothesis_id="H5",
                location="src/labeling/storage.py:get_recent_seed_counts:success",
                message="query executed successfully",
                data={"row_count": len(rows)},
            )
            # endregion
        return {row["card_id"]: row["cnt"] for row in rows}

    def get_pair_last_used_map(self, *, chat_id: int) -> dict[tuple[str, str], datetime]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT card_a, card_b, MAX(used_at) AS last_used_at
                FROM pair_history
                WHERE chat_id = ?
                GROUP BY card_a, card_b
                """,
                (chat_id,),
            ).fetchall()
        result: dict[tuple[str, str], datetime] = {}
        for row in rows:
            normalized = self._normalize_pair(row["card_a"], row["card_b"])
            result[normalized] = datetime.fromisoformat(row["last_used_at"])
        return result

    def trim_pair_history(self, keep_last: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM pair_history
                WHERE rowid NOT IN (
                    SELECT rowid FROM pair_history ORDER BY used_at DESC LIMIT ?
                )
                """,
                (keep_last,),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _ensure_pair_history_chat_scope(conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(pair_history)").fetchall()
        if any(str(row["name"]) == "chat_id" for row in columns):
            return
        conn.execute("ALTER TABLE pair_history ADD COLUMN chat_id INTEGER")

    @staticmethod
    def _embedding_to_blob(embedding: np.ndarray) -> bytes:
        return np.asarray(embedding, dtype=np.float32).tobytes()

    @staticmethod
    def _blob_to_embedding(blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)

    @staticmethod
    def _build_tag_rows(
        card_id: str,
        tags: CardTags,
        dataset_categories: list[str] | None = None,
    ) -> list[tuple[str, str, str]]:
        payload = tags.model_dump(mode="json")
        rows: list[tuple[str, str, str]] = []
        for category, value in payload.items():
            if isinstance(value, list):
                rows.extend((card_id, category, str(item)) for item in value)
            else:
                rows.append((card_id, category, str(value)))
        for dataset_category in LabelingStorage._normalize_categories(dataset_categories):
            rows.append((card_id, "dataset_category", dataset_category))
        return rows

    @staticmethod
    def _normalize_categories(categories: list[str] | None) -> list[str]:
        if not categories:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for category in categories:
            cleaned = category.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    @staticmethod
    def _normalize_pair(card_a: str, card_b: str) -> tuple[str, str]:
        left, right = sorted((card_a, card_b))
        return left, right

    def _row_to_card(self, row: sqlite3.Row) -> CardRecord:
        tags = CardTags.model_validate_json(row["tags_json"])
        return CardRecord(
            id=row["id"],
            name=row["name"],
            wiki_url=row["wiki_url"],
            image_sha256=row["image_sha256"],
            tags=tags,
            appearance_text=row["appearance_text"],
            embedding_model=row["embedding_model"],
            vision_model=row["vision_model"],
            labeled_at=datetime.fromisoformat(row["labeled_at"]),
            dataset_categories=self.get_dataset_categories(row["id"]),
            notes=row["notes"],
        )

