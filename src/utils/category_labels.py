CATEGORY_LABELS: dict[str, str] = {
    "adult": "Актрисы (18+)",
    "anime": "Аниме",
    "cartoons": "Мультфильмы",
    "movies_series": "Кино / Сериалы",
}


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def format_categories(categories: list[str]) -> str:
    return ", ".join(category_label(category) for category in categories)
