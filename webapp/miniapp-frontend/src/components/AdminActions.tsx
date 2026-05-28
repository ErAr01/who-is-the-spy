interface AdminActionItem {
  key: string;
  label: string;
  primary?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onClick: () => void;
}

interface Props {
  title: string;
  actions: AdminActionItem[];
}

export function AdminActions({ title, actions }: Props) {
  if (!actions.length) {
    return null;
  }

  return (
    <section className="card">
      <h2>{title}</h2>
      <div className="actions-col">
        {actions.map((item) => (
          <div key={item.key} className="action-with-reason">
            <button
              type="button"
              className={`button ${item.primary ? "button-primary" : "button-secondary"}`}
              onClick={item.onClick}
              disabled={item.disabled}
              aria-disabled={item.disabled}
            >
              {item.label}
            </button>
            {item.disabled && item.disabledReason ? <p className="hint">{item.disabledReason}</p> : null}
          </div>
        ))}
      </div>
    </section>
  );
}
