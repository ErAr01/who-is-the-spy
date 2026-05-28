import { useMemo, useState } from "react";

import type { MiniAppRoundRolesResponse, MiniAppSnapshot } from "../api/types";
import { AdminActions } from "../components/AdminActions";

interface Props {
  snapshot: MiniAppSnapshot;
  roundRoles: MiniAppRoundRolesResponse | null;
  roundRolesLoading: boolean;
  pendingAction: string | null;
  onRevealRoundRoles: () => void;
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
  roundRoles,
  roundRolesLoading,
  pendingAction,
  onRevealRoundRoles,
  onRepeatRound,
  onCancel
}: Props) {
  const [showCharacterRoles, setShowCharacterRoles] = useState(false);
  const spyName = useMemo(() => resolvePlayerName(snapshot, snapshot.round_spy_id), [snapshot]);
  const votedOutName = useMemo(() => resolvePlayerName(snapshot, snapshot.round_voted_out_id), [snapshot]);
  const canRevealPlayerResults = snapshot.round_spy_id !== null || snapshot.round_voted_out_id !== null;

  return (
    <>
      <section className="card">
        <h2>Итоги</h2>
        <p className="muted">Раунд завершен. Можно обсудить результат и запустить новую игру из чата.</p>
      </section>
      <section className="card">
        <h2>Результаты раунда</h2>
        {canRevealPlayerResults ? (
          <>
            <p>Шпионом был: <strong>{spyName}</strong></p>
            <p>Большинство выбрало: <strong>{votedOutName}</strong></p>
            <p>
              {snapshot.round_is_spy_caught === true
                ? "Мирные победили."
                : snapshot.round_is_spy_caught === false
                  ? "Шпион победил."
                  : "Результат голосования недоступен."}
            </p>
          </>
        ) : (
          <p className="muted">Результаты голосования пока недоступны.</p>
        )}
        <button
          type="button"
          className="button button-secondary"
          onClick={() => {
            if (!showCharacterRoles) {
              void onRevealRoundRoles();
            }
            setShowCharacterRoles(true);
          }}
          disabled={roundRolesLoading || showCharacterRoles}
        >
          {roundRolesLoading ? "Загружаем роли..." : showCharacterRoles ? "Роли показаны" : "Показать роли"}
        </button>
      </section>
      {showCharacterRoles && roundRoles ? (
        <section className="card">
          <h2>Роли персонажей</h2>
          <p><strong>Шпион</strong> — {roundRoles.spy.name ?? "Неизвестно"}</p>
          {roundRoles.spy.image_url ? (
            <img className="card-image" src={roundRoles.spy.image_url} alt={roundRoles.spy.name ?? "Шпион"} loading="lazy" />
          ) : null}
          <p><strong>Мирные</strong> — {roundRoles.civilian.name ?? "Неизвестно"}</p>
          {roundRoles.civilian.image_url ? (
            <img
              className="card-image"
              src={roundRoles.civilian.image_url}
              alt={roundRoles.civilian.name ?? "Мирные"}
              loading="lazy"
            />
          ) : null}
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
