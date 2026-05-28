import { useMemo, useState } from "react";

import type { MiniAppRoleResponse, MiniAppSnapshot } from "../api/types";
import { AdminActions } from "../components/AdminActions";
import { RoleCard } from "../components/RoleCard";

interface Props {
  snapshot: MiniAppSnapshot;
  role: MiniAppRoleResponse | null;
  roleLoading: boolean;
  pendingAction: string | null;
  onRevealRole: () => void;
  onRepeatRound: () => void;
  onCancel: () => void;
}

function resolvePlayerName(snapshot: MiniAppSnapshot, userId: number | null): string {
  if (userId === null) {
    return "Неизвестно";
  }
  return snapshot.players.find((player) => player.user_id === userId)?.name ?? `id=${userId}`;
}

export function FinishedScreen({
  snapshot,
  role,
  roleLoading,
  pendingAction,
  onRevealRole,
  onRepeatRound,
  onCancel
}: Props) {
  const [showRoundResult, setShowRoundResult] = useState(false);
  const spyName = useMemo(() => resolvePlayerName(snapshot, snapshot.round_spy_id), [snapshot]);
  const votedOutName = useMemo(() => resolvePlayerName(snapshot, snapshot.round_voted_out_id), [snapshot]);
  const canRevealRoundResult = snapshot.round_spy_id !== null || snapshot.round_voted_out_id !== null;

  return (
    <>
      <RoleCard role={role} loading={roleLoading} onReveal={onRevealRole} />
      <section className="card">
        <h2>Итоги</h2>
        <p className="muted">Раунд завершен. Можно обсудить результат и запустить новую игру из чата.</p>
        <button
          type="button"
          className="button button-secondary"
          onClick={() => setShowRoundResult(true)}
          disabled={!canRevealRoundResult || showRoundResult}
        >
          {showRoundResult ? "Роли показаны" : "Показать роли"}
        </button>
      </section>
      {showRoundResult ? (
        <section className="card">
          <h2>Результаты раунда</h2>
          <p>Шпионом был: <strong>{spyName}</strong></p>
          <p>Большинство выбрало: <strong>{votedOutName}</strong></p>
          <p>
            {snapshot.round_is_spy_caught === true
              ? "Мирные победили."
              : snapshot.round_is_spy_caught === false
                ? "Шпион победил."
                : "Результат голосования недоступен."}
          </p>
        </section>
      ) : null}
      <AdminActions
        title="Действия админа"
        actions={[
          {
            key: "repeat-round",
            label: "Еще раунд",
            primary: true,
            disabled: !snapshot.is_admin || pendingAction !== null,
            disabledReason: !snapshot.is_admin ? "Только админ может запустить следующий раунд" : undefined,
            onClick: onRepeatRound
          },
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
