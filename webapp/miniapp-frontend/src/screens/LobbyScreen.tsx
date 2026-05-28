import type { MiniAppSnapshot } from "../api/types";
import { AdminActions } from "../components/AdminActions";
import { CategoriesPanel } from "../components/CategoriesPanel";
import { PlayersList } from "../components/PlayersList";

interface Props {
  snapshot: MiniAppSnapshot;
  pendingAction: string | null;
  onJoin: () => void;
  onToggleCategory: (category: string) => void;
  onStart: () => void;
  onCancel: () => void;
}

export function LobbyScreen({ snapshot, pendingAction, onJoin, onToggleCategory, onStart, onCancel }: Props) {
  const isAdmin = snapshot.is_admin;
  const isMember = snapshot.is_member;

  const joinDisabledReason = isMember ? "Вы уже в игре" : undefined;

  return (
    <>
      <PlayersList players={snapshot.players} adminId={snapshot.admin_id} />

      {!isMember ? (
        <section className="card">
          <h2>Присоединение</h2>
          <button type="button" className="button button-primary" onClick={onJoin} disabled={pendingAction === "join"}>
            {pendingAction === "join" ? "Присоединяем..." : "Присоединиться к игре"}
          </button>
          {joinDisabledReason ? <p className="hint">{joinDisabledReason}</p> : null}
        </section>
      ) : null}

      <CategoriesPanel
        available={snapshot.available_categories}
        selected={snapshot.selected_categories}
        canEdit={isAdmin}
        disabledReason="Только админ может менять категории"
        pending={pendingAction === "toggle_category"}
        onToggle={onToggleCategory}
      />

      <AdminActions
        title="Действия админа"
        actions={[
          {
            key: "start",
            label: "Начать раунд",
            primary: true,
            disabled: !isAdmin || snapshot.players.length < 3 || pendingAction !== null,
            disabledReason: !isAdmin
              ? "Доступно только админу"
              : snapshot.players.length < 3
                ? "Нужно минимум 3 игрока"
                : undefined,
            onClick: onStart
          },
          {
            key: "cancel",
            label: "Отменить игру",
            disabled: !isAdmin || pendingAction !== null,
            disabledReason: !isAdmin ? "Доступно только админу" : undefined,
            onClick: onCancel
          }
        ]}
      />
    </>
  );
}
