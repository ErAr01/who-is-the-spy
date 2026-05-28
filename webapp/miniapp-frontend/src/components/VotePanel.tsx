import type { MiniAppPlayer } from "../api/types";

interface Props {
  players: MiniAppPlayer[];
  currentUserId: number;
  disabled: boolean;
  disabledReason?: string;
  onVote: (targetId: number) => void;
}

export function VotePanel({ players, currentUserId, disabled, disabledReason, onVote }: Props) {
  const targets = players.filter((player) => player.user_id !== currentUserId);

  return (
    <section className="card">
      <h2>Голосование</h2>
      {targets.length === 0 ? <p className="muted">Недостаточно игроков для голоса.</p> : null}
      <div className="actions-col">
        {targets.map((target) => (
          <button
            key={target.user_id}
            type="button"
            className="button button-secondary"
            disabled={disabled}
            aria-disabled={disabled}
            onClick={() => onVote(target.user_id)}
          >
            Голос за {target.name}
          </button>
        ))}
      </div>
      {disabled && disabledReason ? <p className="hint">{disabledReason}</p> : null}
    </section>
  );
}
