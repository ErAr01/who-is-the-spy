import type { ConnectionState, GameState } from "../api/types";

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  loading: "Загрузка",
  fresh: "Онлайн",
  stale: "Соединение нестабильно",
  reconnecting: "Переподключение"
};

const STATE_LABEL: Record<GameState, string> = {
  lobby: "Лобби",
  custom_setup: "Лобби",
  playing: "Раунд",
  voting: "Голосование",
  finished: "Финиш"
};

interface Props {
  gameState: GameState | null;
  connection: ConnectionState;
}

export function TopStatusBar({ gameState, connection }: Props) {
  return (
    <header className="status-bar" role="status" aria-live="polite">
      <span className={`chip chip-${connection}`}>{CONNECTION_LABEL[connection]}</span>
      <span className="chip chip-state">{gameState ? STATE_LABEL[gameState] : "Состояние неизвестно"}</span>
    </header>
  );
}
