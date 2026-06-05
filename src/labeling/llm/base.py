from dataclasses import dataclass
from typing import Protocol

import numpy as np

from src.labeling.models import CardTags


@dataclass(slots=True)
class TaggingResult:
    tags: CardTags
    usage: dict[str, int]
    estimated_cost_usd: float


@dataclass(slots=True)
class EmbeddingResult:
    vector: np.ndarray
    usage: dict[str, int]
    estimated_cost_usd: float


@dataclass(slots=True)
class DescriptionResult:
    description: str
    facts: list[str]
    usage: dict[str, int]
    estimated_cost_usd: float


class LLMTagger(Protocol):
    def tag_image(self, image_bytes: bytes, name: str) -> TaggingResult:
        raise NotImplementedError

    def build_appearance_text(self, tags: CardTags) -> str:
        raise NotImplementedError


class Embedder(Protocol):
    def embed_text(self, text: str) -> EmbeddingResult:
        raise NotImplementedError


class CharacterDescriber(Protocol):
    def describe(
        self,
        name: str,
        categories: list[str],
        appearance_text: str | None = None,
        wiki_url: str | None = None,
        notes: str | None = None,
    ) -> DescriptionResult:
        raise NotImplementedError

