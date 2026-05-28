import type { MiniAppRoleResponse, MiniAppRoundRoleCard, MiniAppRoundRolesResponse, MiniAppSnapshot } from "../api/types";
import { AdminActions } from "../components/AdminActions";
import { PlayersList } from "../components/PlayersList";
import { RoleCard } from "../components/RoleCard";

interface Props {
  snapshot: MiniAppSnapshot;
  role: MiniAppRoleResponse | null;
  roleLoading: boolean;
  roundRoles: MiniAppRoundRolesResponse | null;
  roundRolesLoading: boolean;
  pendingAction: string | null;
  onRevealRole: () => void;
  onRevealRoundRoles: () => void;
  onCancel: () => void;
}

function RoundRoleCard({ title, card }: { title: string; card: MiniAppRoundRoleCard }) {
  return (
    <section className="card">
      <h3>{title}</h3>
      {card.image_url ? <img className="card-image" src={card.image_url} alt={card.name ?? title} loading="lazy" /> : null}
      <p>
        <strong>{card.name ?? "Персонаж недоступен"}</strong>
      </p>
      {card.category_label ? <p className="hint">Категория: {card.category_label}</p> : null}
      <div className="actions-col">
        {card.wiki_url ? (
          <a className="button button-secondary" href={card.wiki_url} target="_blank" rel="noreferrer">
            Wikipedia
          </a>
        ) : null}
        {card.search_url ? (
          <a className="button button-secondary" href={card.search_url} target="_blank" rel="noreferrer">
            Искать в Google
          </a>
        ) : null}
      </div>
    </section>
  );
}

export function FinishedScreen({
  snapshot,
  role,
  roleLoading,
  roundRoles,
  roundRolesLoading,
  pendingAction,
  onRevealRole,
  onRevealRoundRoles,
  onCancel
}: Props) {
  return (
    <>
      <RoleCard role={role} loading={roleLoading} onReveal={onRevealRole} />
      <PlayersList players={snapshot.players} adminId={snapshot.admin_id} />
      <section className="card">
        <h2>Итоги</h2>
        <p className="muted">Раунд завершен. Можно обсудить результат и запустить новую игру из чата.</p>
        <button
          type="button"
          className="button button-secondary"
          onClick={onRevealRoundRoles}
          disabled={roundRolesLoading || pendingAction !== null}
        >
          {roundRolesLoading ? "Загружаем роли..." : "Показать роли"}
        </button>
      </section>
      {roundRoles ? (
        <>
          {roundRoles.theme ? (
            <section className="card">
              <h2>Тема раунда</h2>
              <p>{roundRoles.theme}</p>
            </section>
          ) : null}
          <RoundRoleCard title="Персонаж мирных жителей" card={roundRoles.civilian} />
          <RoundRoleCard title="Персонаж шпиона" card={roundRoles.spy} />
        </>
      ) : null}
      <section className="card">
        <p className="hint">
          Роли раунда раскрываются только по кнопке, чтобы не спойлерить обсуждение сразу после завершения голосования.
        </p>
      </section>
      <AdminActions
        title="Действия админа"
        actions={[
          {
            key: "cancel-game",
            label: "Сбросить игру",
            disabled: !snapshot.is_admin || pendingAction !== null,
            disabledReason: !snapshot.is_admin ? "Только админ может сбросить игру" : undefined,
            onClick: onCancel
          }
        ]}
      />
    </>
  );
}
