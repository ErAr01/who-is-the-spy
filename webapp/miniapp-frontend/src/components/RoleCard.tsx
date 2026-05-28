import type { MiniAppRoleResponse } from "../api/types";

interface Props {
  role: MiniAppRoleResponse | null;
  loading: boolean;
  onReveal: () => void;
  hiddenReason?: string;
}

export function RoleCard({ role, loading, onReveal, hiddenReason }: Props) {
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
          <p className="role-name">{role.role_name ?? (role.is_spy ? "Шпион" : "Мирный")}</p>
          <p className="role-payload">{role.payload ?? "payload недоступен"}</p>
        </div>
      )}
      <button type="button" className="button button-secondary" onClick={onReveal} disabled={loading}>
        {loading ? "Загружаем..." : "Показать роль"}
      </button>
    </section>
  );
}
