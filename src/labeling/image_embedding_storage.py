import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np


@dataclass(slots=True)
class ImageEmbeddingRecord:
    card_id: str
    image_sha256: str
    file_path: str | None
    embedding: np.ndarray
    model: str
    dimension: int
    created_at: datetime
    updated_at: datetime


class ImageEmbeddingStorage:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS image_embeddings (
                    image_sha256 TEXT PRIMARY KEY,
                    card_id      TEXT NOT NULL UNIQUE,
                    file_path    TEXT,
                    embedding    BLOB NOT NULL,
                    model        TEXT NOT NULL,
                    dimension    INTEGER NOT NULL,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_image_embeddings_card_id ON image_embeddings(card_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_image_embeddings_updated_at ON image_embeddings(updated_at DESC)")
            conn.commit()

    @staticmethod
    def sha256_digest(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def upsert_embedding(
        self,
        *,
        card_id: str,
        image_sha256: str,
        file_path: str | None,
        embedding: np.ndarray,
        model: str,
    ) -> ImageEmbeddingRecord:
        vector = np.asarray(embedding, dtype=np.float32)
        if vector.ndim != 1:
            raise ValueError("Embedding must be a 1D vector")

        now_iso = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO image_embeddings (
                    image_sha256, card_id, file_path, embedding, model, dimension, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(image_sha256) DO UPDATE SET
                    card_id=excluded.card_id,
                    file_path=excluded.file_path,
                    embedding=excluded.embedding,
                    model=excluded.model,
                    dimension=excluded.dimension,
                    updated_at=excluded.updated_at
                """,
                (
                    image_sha256,
                    card_id,
                    file_path,
                    vector.tobytes(),
                    model,
                    int(vector.shape[0]),
                    now_iso,
                    now_iso,
                ),
            )
            row = conn.execute(
                """
                SELECT image_sha256, card_id, file_path, embedding, model, dimension, created_at, updated_at
                FROM image_embeddings
                WHERE image_sha256 = ?
                """,
                (image_sha256,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Unable to read upserted image embedding record")
        return self._row_to_record(row)

    def get_by_sha256(self, image_sha256: str) -> ImageEmbeddingRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT image_sha256, card_id, file_path, embedding, model, dimension, created_at, updated_at
                FROM image_embeddings
                WHERE image_sha256 = ?
                """,
                (image_sha256,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_card_id(self, card_id: str) -> ImageEmbeddingRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT image_sha256, card_id, file_path, embedding, model, dimension, created_at, updated_at
                FROM image_embeddings
                WHERE card_id = ?
                """,
                (card_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_records(self) -> list[ImageEmbeddingRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT image_sha256, card_id, file_path, embedding, model, dimension, created_at, updated_at
                FROM image_embeddings
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ImageEmbeddingRecord:
        return ImageEmbeddingRecord(
            card_id=str(row["card_id"]),
            image_sha256=str(row["image_sha256"]),
            file_path=str(row["file_path"]) if row["file_path"] is not None else None,
            embedding=np.frombuffer(row["embedding"], dtype=np.float32),
            model=str(row["model"]),
            dimension=int(row["dimension"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
