const CATEGORY_LABELS: Record<string, string> = {
  adult: "Актрисы (18+)",
  anime: "Аниме",
  cartoons: "Мультфильмы",
  musicians: "Музыканты",
  movies_series: "Кино / Сериалы"
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}
