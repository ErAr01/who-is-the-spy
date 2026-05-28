interface Props {
  available: string[];
  selected: string[];
  canEdit: boolean;
  disabledReason?: string;
  pending: boolean;
  onToggle: (category: string) => void;
}

export function CategoriesPanel({ available, selected, canEdit, disabledReason, pending, onToggle }: Props) {
  return (
    <section className="card">
      <h2>Категории</h2>
      {available.length === 0 ? <p className="muted">Категории не заданы.</p> : null}
      <div className="chip-grid">
        {available.map((category) => {
          const active = selected.includes(category);
          return (
            <button
              key={category}
              type="button"
              className={`chip-button ${active ? "active" : ""}`}
              disabled={!canEdit || pending}
              aria-disabled={!canEdit || pending}
              title={!canEdit ? disabledReason : undefined}
              onClick={() => onToggle(category)}
            >
              {category}
            </button>
          );
        })}
      </div>
      {!canEdit && disabledReason ? <p className="hint">{disabledReason}</p> : null}
    </section>
  );
}
