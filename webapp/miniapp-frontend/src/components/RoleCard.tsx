import type { MiniAppRoleResponse } from "../api/types";

interface Props {
  role: MiniAppRoleResponse | null;
  loading: boolean;
  onReveal: () => void;
  hiddenReason?: string;
}

export function RoleCard({ role, loading, onReveal, hiddenReason }: Props) {
  const roleTitle = role?.role_name ?? (role?.is_spy ? "Шпион" : "Мирный");

  return (
    <section className="card role-card">
      <h2>Твоя роль</h2>
      {!role?.has_role ? (
        <div>
          <p className="muted">Роль скрыта до старта раунда.</p>
          {hiddenReason ? <p className="hint">{hiddenReason}</p> : null}
        </div>
      ) : (
        <div>
          <p className="role-name">{roleTitle}</p>
          {role.image_url ? <img className="card-image" src={role.image_url} alt={roleTitle} loading="lazy" /> : null}
          {role.category_label ? <p className="hint">Категория: {role.category_label}</p> : null}
          {role.payload ? <p className="role-payload">{role.payload}</p> : null}
          <div className="actions-col">
            {role.wiki_url ? (
              <a className="button button-secondary" href={role.wiki_url} target="_blank" rel="noreferrer">
                Wikipedia
              </a>
            ) : null}
            {role.search_url ? (
              <a className="button button-secondary" href={role.search_url} target="_blank" rel="noreferrer">
                Искать в Google
              </a>
            ) : null}
          </div>
        </div>
      )}
      <button type="button" className="button button-secondary" onClick={onReveal} disabled={loading}>
        {loading ? "Загружаем..." : "Показать роль"}
      </button>
    </section>
  );
}
