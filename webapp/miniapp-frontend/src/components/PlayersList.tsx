import type { MiniAppPlayer } from "../api/types";

interface Props {
  players: MiniAppPlayer[];
  adminId: number;
  canManage: boolean;
  pending: boolean;
  onRequestKick: (player: MiniAppPlayer) => void;
}

export function PlayersList({ players, adminId, canManage, pending, onRequestKick }: Props) {
  return (
    <section className="card">
      <h2>Игроки</h2>
      {players.length === 0 ? <p className="muted">Пока никто не присоединился.</p> : null}
      <ul className="list">
        {players.map((player) => (
          <li key={player.user_id} className="list-item">
            <span>{player.name}</span>
            {player.user_id === adminId ? (
              <span className="chip">Админ</span>
            ) : canManage ? (
              <button
                type="button"
                className="button button-secondary list-inline-button"
                disabled={pending}
                onClick={() => onRequestKick(player)}
              >
                Удалить
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
