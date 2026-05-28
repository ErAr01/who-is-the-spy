import type { MiniAppPlayer } from "../api/types";

interface Props {
  players: MiniAppPlayer[];
  adminId: number;
}

export function PlayersList({ players, adminId }: Props) {
  return (
    <section className="card">
      <h2>Игроки</h2>
      {players.length === 0 ? <p className="muted">Пока никто не присоединился.</p> : null}
      <ul className="list">
        {players.map((player) => (
          <li key={player.user_id} className="list-item">
            <span>{player.name}</span>
            {player.user_id === adminId ? <span className="chip">Админ</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
