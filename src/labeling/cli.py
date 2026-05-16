import json
import re
from pathlib import Path

import numpy as np
import typer

from src.config import get_settings
from src.labeling.image_embedding_pipeline import ImageEmbeddingPipeline
from src.labeling.image_embedding_provider import (
    LocalClipImageEmbeddingProvider,
    OpenAIImageEmbeddingProvider,
)
from src.labeling.image_embedding_storage import ImageEmbeddingStorage
from src.labeling.llm.openai_tagger import OpenAITagger
from src.labeling.pipeline import LabelingPipeline
from src.labeling.similarity import PairSelector
from src.labeling.storage import LabelingStorage

app = typer.Typer(help="Card labeling service CLI")


def _storage() -> LabelingStorage:
    settings = get_settings()
    storage = LabelingStorage(settings.labeling_db_path)
    storage.init_db()
    return storage


def _pipeline(vision_model: str | None = None, embedding_model: str | None = None) -> LabelingPipeline:
    settings = get_settings()
    if settings.openai_api_key is None:
        raise typer.BadParameter("OPENAI_API_KEY is required for labeling commands")
    tagger = OpenAITagger(
        api_key=settings.openai_api_key.get_secret_value(),
        vision_model=vision_model or settings.openai_vision_model,
        embedding_model=embedding_model or settings.openai_embedding_model,
    )
    return LabelingPipeline(_storage(), tagger, tagger)


def _image_embedding_storage() -> ImageEmbeddingStorage:
    settings = get_settings()
    storage = ImageEmbeddingStorage(settings.image_embedding_db_path)
    storage.init_db()
    return storage


def _image_embedding_provider(provider_name: str | None = None):
    settings = get_settings()
    selected_provider = (provider_name or settings.image_embedding_provider).strip().lower()
    if selected_provider == "local_clip":
        return LocalClipImageEmbeddingProvider(
            model_name=settings.local_clip_model_name,
            device=settings.image_embedding_device,
        )
    if selected_provider == "openai":
        if settings.openai_api_key is None:
            raise typer.BadParameter("OPENAI_API_KEY is required when IMAGE_EMBEDDING_PROVIDER=openai")
        return OpenAIImageEmbeddingProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_embedding_model,
        )
    raise typer.BadParameter(
        f"Unsupported IMAGE_EMBEDDING_PROVIDER='{selected_provider}'. Supported values: local_clip, openai."
    )


def _image_embedding_pipeline(provider_name: str | None = None) -> ImageEmbeddingPipeline:
    # 📚 Что здесь происходит:
    # Мы поднимаем отдельный pipeline именно для image-image embeddings:
    # legacy карточки остаются в `cards.db`, а векторные "отпечатки" изображений
    # складываются в отдельную БД. Это как две полки в архиве: одна для карточек,
    # другая только для быстрых image-lookup экспериментов.
    #
    # ⚠️ Важно знать:
    # - Card ID должен уже существовать в legacy cards DB, иначе пайплайн прервётся.
    # - Локальный CLIP работает без внешнего API, но требует `torch + transformers`.
    return ImageEmbeddingPipeline(
        storage=_image_embedding_storage(),
        provider=_image_embedding_provider(provider_name=provider_name),
        legacy_normalizer=_storage(),
    )


def _normalize_categories(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        cleaned = item.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _humanize_stem(stem: str) -> str:
    collapsed = re.sub(r"[-_]+", " ", stem).strip()
    return collapsed.title() if collapsed else stem


def _pca_2d(matrix: np.ndarray) -> np.ndarray:
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    coords = centered @ vt[:2].T
    return coords


# High-contrast palette for main dataset categories.
_CATEGORY_COLORS: dict[str, str] = {
    "anime": "#e41a1c",  # red
    "cartoons": "#377eb8",  # blue
    "adult": "#4daf4a",  # green
    "movies_series": "#ff7f00",  # orange
    "smoke": "#984ea3",  # purple
    "uncategorized": "#555555",  # gray
}

_FALLBACK_COLORS: list[str] = [
    "#a65628",
    "#f781bf",
    "#999999",
    "#66c2a5",
    "#fc8d62",
    "#8da0cb",
    "#e78ac3",
    "#a6d854",
    "#ffd92f",
    "#e5c494",
]


@app.command("ingest")
def ingest(
    image: Path = typer.Option(..., exists=True, dir_okay=False),
    name: str = typer.Option(...),
    wiki: str | None = typer.Option(None),
    card_id: str | None = typer.Option(None, "--id"),
    category: list[str] = typer.Option([], "--category"),
    force: bool = typer.Option(False),
) -> None:
    pipeline = _pipeline()
    result = pipeline.ingest_card(
        image_bytes=image.read_bytes(),
        name=name,
        wiki_url=wiki,
        card_id=card_id,
        categories=_normalize_categories(category),
        force=force,
    )
    if result.skipped_duplicate:
        typer.echo(f"Skipped duplicate image, existing card id: {result.card.id}")
    else:
        typer.echo(f"Ingested card: {result.card.id}")


@app.command("ingest-batch")
def ingest_batch(
    dir_path: Path = typer.Option(..., "--dir", exists=True, file_okay=False),
    category: list[str] = typer.Option([], "--category"),
    force: bool = typer.Option(False),
) -> None:
    pipeline = _pipeline()
    allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}
    default_categories = _normalize_categories(category)
    attempted = 0
    processed = 0
    skipped = 0
    failed = 0
    for image_path in sorted(dir_path.iterdir()):
        if image_path.suffix.lower() not in allowed_ext:
            continue
        attempted += 1
        sidecar = image_path.with_suffix(".json")
        name = _humanize_stem(image_path.stem)
        wiki_url = None
        card_id = None
        categories = list(default_categories)
        if sidecar.exists():
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            name = payload.get("name", name)
            wiki_url = payload.get("wiki_url")
            card_id = payload.get("id")
            sidecar_categories = payload.get("categories")
            if isinstance(sidecar_categories, list):
                categories.extend(str(item) for item in sidecar_categories)
            elif isinstance(sidecar_categories, str):
                categories.append(sidecar_categories)

        try:
            result = pipeline.ingest_card(
                image_bytes=image_path.read_bytes(),
                name=name,
                wiki_url=wiki_url,
                card_id=card_id,
                categories=_normalize_categories(categories),
                force=force,
            )
        except Exception as exc:
            failed += 1
            typer.echo(f"{image_path.name} -> ERROR ({type(exc).__name__}): {exc}")
            continue
        processed += 1
        skipped += int(result.skipped_duplicate)
        typer.echo(f"{image_path.name} -> {result.card.id}")
    typer.echo(
        f"Done. Attempted={attempted}, processed={processed}, failed={failed}, skipped_duplicates={skipped}"
    )


@app.command("image-embed-ingest")
def image_embed_ingest(
    image: Path = typer.Option(..., "--image", exists=True, dir_okay=False),
    card_id: str | None = typer.Option(None, "--id"),
    force: bool = typer.Option(False),
    provider: str | None = typer.Option(None, "--provider"),
) -> None:
    pipeline = _image_embedding_pipeline(provider_name=provider)
    resolved_card_id = card_id or image.stem
    result = pipeline.ingest_image(
        image_bytes=image.read_bytes(),
        card_id=resolved_card_id,
        file_path=str(image),
        force=force,
    )
    if result.skipped_duplicate:
        typer.echo(
            f"Skipped duplicate image embedding: card_id={result.record.card_id} sha256={result.record.image_sha256}"
        )
        return
    typer.echo(
        f"Ingested image embedding: card_id={result.record.card_id} "
        f"model={result.record.model} dim={result.record.dimension}"
    )


@app.command("image-embed-ingest-batch")
def image_embed_ingest_batch(
    dir_path: Path = typer.Option(..., "--dir", exists=True, file_okay=False),
    force: bool = typer.Option(False),
    provider: str | None = typer.Option(None, "--provider"),
) -> None:
    pipeline = _image_embedding_pipeline(provider_name=provider)
    allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}
    attempted = 0
    processed = 0
    skipped = 0
    failed = 0
    for image_path in sorted(dir_path.iterdir()):
        if image_path.suffix.lower() not in allowed_ext:
            continue
        attempted += 1
        resolved_card_id = image_path.stem
        try:
            result = pipeline.ingest_image(
                image_bytes=image_path.read_bytes(),
                card_id=resolved_card_id,
                file_path=str(image_path),
                force=force,
            )
        except Exception as exc:
            failed += 1
            typer.echo(f"{image_path.name} -> ERROR ({type(exc).__name__}): {exc}")
            continue
        processed += 1
        skipped += int(result.skipped_duplicate)
        typer.echo(
            f"{image_path.name} -> card_id={result.record.card_id} "
            f"model={result.record.model} dim={result.record.dimension}"
        )
    typer.echo(
        f"Done. Attempted={attempted}, processed={processed}, failed={failed}, skipped_duplicates={skipped}"
    )


@app.command("image-embed-reembed")
def image_embed_reembed(
    image: Path = typer.Option(..., "--image", exists=True, dir_okay=False),
    card_id: str | None = typer.Option(None, "--id"),
    provider: str | None = typer.Option(None, "--provider"),
) -> None:
    pipeline = _image_embedding_pipeline(provider_name=provider)
    resolved_card_id = card_id or image.stem
    record = pipeline.reembed_image(
        image_bytes=image.read_bytes(),
        card_id=resolved_card_id,
        file_path=str(image),
    )
    typer.echo(
        f"Re-embedded image: card_id={record.card_id} model={record.model} dim={record.dimension}"
    )


@app.command("image-embed-list")
def image_embed_list(output_format: str = typer.Option("table", "--format")) -> None:
    records = _image_embedding_storage().list_records()
    if output_format == "json":
        payload = [
            {
                "card_id": record.card_id,
                "image_sha256": record.image_sha256,
                "file_path": record.file_path,
                "model": record.model,
                "dimension": record.dimension,
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
            }
            for record in records
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for record in records:
        typer.echo(
            f"{record.card_id:24} | {record.model:32} | dim={record.dimension:4} | {record.updated_at.isoformat()}"
        )


@app.command("relabel")
def relabel(
    card_id: str | None = typer.Option(None, "--id"),
    all_cards: bool = typer.Option(False, "--all"),
    vision_model: str | None = typer.Option(None, "--vision-model"),
) -> None:
    pipeline = _pipeline(vision_model=vision_model)
    if all_cards:
        cards = pipeline.relabel_all()
        typer.echo(f"Relabeled {len(cards)} cards")
        return
    if not card_id:
        raise typer.BadParameter("Provide --id or --all")
    card = pipeline.relabel_card(card_id)
    typer.echo(f"Relabeled card: {card.id}")


@app.command("re-embed")
def re_embed(
    card_id: str | None = typer.Option(None, "--id"),
    all_cards: bool = typer.Option(False, "--all"),
) -> None:
    pipeline = _pipeline()
    if all_cards:
        cards = pipeline.re_embed_all()
        typer.echo(f"Re-embedded {len(cards)} cards")
        return
    if not card_id:
        raise typer.BadParameter("Provide --id or --all")
    card = pipeline.re_embed_card(card_id)
    typer.echo(f"Re-embedded card: {card.id}")


@app.command("list")
def list_cards(
    output_format: str = typer.Option("table", "--format"),
    filter_expr: str | None = typer.Option(None, "--filter"),
) -> None:
    cards = _storage().list_cards()
    if filter_expr:
        key, sep, value = filter_expr.partition("=")
        if not sep:
            raise typer.BadParameter("Filter must be key=value")
        if key == "dataset_category":
            cards = [card for card in cards if value in card.dataset_categories]
        else:
            cards = [
                card
                for card in cards
                if str(card.tags.model_dump(mode="json").get(key, "")) == value
                or str(getattr(card, key, "")) == value
            ]
    if output_format == "json":
        payload = [card.model_dump(mode="json") for card in cards]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for card in cards:
        categories = ",".join(card.dataset_categories) or "-"
        typer.echo(f"{card.id:24} | {card.name:32} | {categories:24} | {card.labeled_at.isoformat()}")


@app.command("show")
def show(card_id: str = typer.Option(..., "--id")) -> None:
    storage = _storage()
    card = storage.get_card(card_id)
    if card is None:
        raise typer.BadParameter(f"Card '{card_id}' not found")
    image = storage.get_image_bytes(card_id)
    thumb = storage.get_image_bytes(card_id, thumbnail=True)
    typer.echo(json.dumps(card.model_dump(mode="json"), ensure_ascii=False, indent=2))
    typer.echo(f"image_bytes={len(image or b'')} thumbnail_bytes={len(thumb or b'')}")


@app.command("pair")
def pair(seed_id: str | None = typer.Option(None, "--seed-id")) -> None:
    settings = get_settings()
    selector = PairSelector(
        storage=_storage(),
        threshold=settings.pair_similarity_threshold,
        pair_history_size=settings.pair_history_size,
        pair_selection_mode=settings.pair_selection_mode,
        pair_seed_retry_limit=settings.pair_seed_retry_limit,
        pair_logprob_threshold=settings.pair_logprob_threshold,
    )
    result = selector.pick_pair(seed_id=seed_id)
    typer.echo(f"{result.card_a.id} <-> {result.card_b.id} | similarity={result.similarity:.4f} | k={result.k_used}")


@app.command("export-images")
def export_images(
    dir_path: Path = typer.Option(..., "--dir"),
    ids: str | None = typer.Option(None, "--ids"),
) -> None:
    storage = _storage()
    dir_path.mkdir(parents=True, exist_ok=True)
    requested_ids = set(ids.split(",")) if ids else None
    exported = 0
    for card in storage.list_cards():
        if requested_ids is not None and card.id not in requested_ids:
            continue
        image = storage.get_image_bytes(card.id)
        if image is None:
            continue
        (dir_path / f"{card.id}.jpg").write_bytes(image)
        exported += 1
    typer.echo(f"Exported {exported} images to {dir_path}")


@app.command("stats")
def stats() -> None:
    cards = _storage().list_cards()
    if not cards:
        typer.echo("No cards in database")
        return
    tag_counts: dict[str, int] = {}
    for card in cards:
        for key, value in card.tags.model_dump(mode="json").items():
            if isinstance(value, list):
                for item in value:
                    tag_counts[f"{key}:{item}"] = tag_counts.get(f"{key}:{item}", 0) + 1
            else:
                tag_counts[f"{key}:{value}"] = tag_counts.get(f"{key}:{value}", 0) + 1
    typer.echo(f"cards={len(cards)}")
    for key, count in sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)[:20]:
        typer.echo(f"{key} -> {count}")


@app.command("plot-embeddings")
def plot_embeddings(
    out_path: Path = typer.Option(Path("data/images/embeddings_2d.png"), "--out"),
    category: list[str] = typer.Option([], "--category"),
    with_labels: bool = typer.Option(False, "--with-labels"),
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise typer.BadParameter(
            "matplotlib is required. Install it with: pip install matplotlib"
        ) from exc

    storage = _storage()
    cards = storage.list_cards()
    category_filter = set(_normalize_categories(category))
    selected_cards = [
        card
        for card in cards
        if not category_filter or category_filter.intersection(set(card.dataset_categories))
    ]
    if len(selected_cards) < 2:
        raise typer.BadParameter("Need at least 2 cards to plot embeddings.")

    embeddings_by_id = dict(storage.load_all_embeddings())
    points: list[np.ndarray] = []
    labels: list[str] = []
    colors_by_card: list[str] = []
    for card in selected_cards:
        vector = embeddings_by_id.get(card.id)
        if vector is None:
            continue
        points.append(vector)
        labels.append(card.name)
        colors_by_card.append(card.dataset_categories[0] if card.dataset_categories else "uncategorized")

    if len(points) < 2:
        raise typer.BadParameter("Not enough embeddings in DB for selected cards.")

    matrix = np.vstack(points)
    coords = _pca_2d(matrix)

    unique_categories = sorted(set(colors_by_card))
    color_map: dict[str, str] = {}
    fallback_idx = 0
    for name in unique_categories:
        predefined = _CATEGORY_COLORS.get(name)
        if predefined is not None:
            color_map[name] = predefined
            continue
        color_map[name] = _FALLBACK_COLORS[fallback_idx % len(_FALLBACK_COLORS)]
        fallback_idx += 1
    plotted_colors = [color_map[name] for name in colors_by_card]

    fig, ax = plt.subplots(figsize=(12, 8))
    ax.scatter(coords[:, 0], coords[:, 1], c=plotted_colors, s=40, alpha=0.85, edgecolors="#111111", linewidths=0.2)
    ax.set_title("Card Embeddings (PCA 2D)")
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.grid(alpha=0.25)

    if with_labels:
        for i, label in enumerate(labels):
            ax.annotate(label, (coords[i, 0], coords[i, 1]), fontsize=7, alpha=0.8)

    handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=color_map[name], label=name, markersize=8)
        for name in unique_categories
    ]
    if handles:
        ax.legend(handles=handles, title="dataset_category", loc="best")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    typer.echo(f"Saved 2D embedding plot to {out_path} (cards={len(points)})")


if __name__ == "__main__":
    app()

