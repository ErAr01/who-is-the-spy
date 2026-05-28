import { useMemo, useState } from "react";

import type { MiniAppPlayer, MiniAppSnapshot } from "../api/types";
import { AdminActions } from "../components/AdminActions";
import { CategoriesPanel } from "../components/CategoriesPanel";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PlayersList } from "../components/PlayersList";

interface Props {
  snapshot: MiniAppSnapshot;
  pendingAction: string | null;
  onJoin: () => void;
  onLeave: () => void;
  onKickPlayer: (targetId: number) => void;
  onToggleCategory: (category: string) => void;
  onStart: () => void;
  onCancel: () => void;
}

export function LobbyScreen({
  snapshot,
  pendingAction,
  onJoin,
  onLeave,
  onKickPlayer,
  onToggleCategory,
  onStart,
  onCancel
}: Props) {
  const [kickCandidate, setKickCandidate] = useState<MiniAppPlayer | null>(null);
  const isAdmin = snapshot.is_admin;
  const isMember = snapshot.is_member;
  const waitsNextRound = isMember && !snapshot.is_in_current_round;
  const kickInProgress = pendingAction === "kick_player";
  const kickDescription = useMemo(() => {
    if (!kickCandidate) {
      return "";
    }
    return `Игрок ${kickCandidate.name} будет исключен из текущего лобби.`;
  }, [kickCandidate]);

  const joinDisabledReason = isMember ? "Вы уже в игре" : undefined;

  return (
    <>
      <PlayersList
        players={snapshot.players}
        adminId={snapshot.admin_id}
        canManage={isAdmin}
        pending={pendingAction !== null}
        onRequestKick={(player) => setKickCandidate(player)}
      />

      {!isMember ? (
        <section className="card">
          <h2>Присоединение</h2>
          <button type="button" className="button button-primary" onClick={onJoin} disabled={pendingAction === "join"}>
            {pendingAction === "join" ? "Присоединяем..." : "Присоединиться к игре"}
          </button>
          {joinDisabledReason ? <p className="hint">{joinDisabledReason}</p> : null}
        </section>
      ) : null}

      {isMember ? (
        <section className="card">
          <h2>Лобби</h2>
          <button
            type="button"
            className="button button-secondary"
            onClick={onLeave}
            disabled={pendingAction === "leave" || isAdmin}
          >
            {pendingAction === "leave" ? "Выходим..." : "Покинуть лобби"}
          </button>
          {isAdmin ? <p className="hint">Админ не может выйти из лобби, пока активна эта игра.</p> : null}
        </section>
      ) : null}

      {waitsNextRound ? (
        <section className="card">
          <p className="hint">Вы уже в лобби. В текущий раунд вход закрыт, участие начнется со следующего.</p>
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
      <ConfirmDialog
        open={kickCandidate !== null}
        title="Удалить игрока из лобби?"
        description={kickDescription}
        confirmText={kickInProgress ? "Удаляем..." : "Удалить"}
        onCancel={() => setKickCandidate(null)}
        onConfirm={() => {
          if (!kickCandidate || kickInProgress) {
            return;
          }
          onKickPlayer(kickCandidate.user_id);
          setKickCandidate(null);
        }}
      />
    </>
  );
}
