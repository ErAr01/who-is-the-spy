import { mapError } from "../api/errorMap";
import type { ApiError } from "../api/types";

interface Props {
  loading: boolean;
  error: ApiError | null;
  hasTelegramContext: boolean;
  hasChatId: boolean;
  onRetry: () => void;
}

export function AuthGatePage({ loading, error, hasTelegramContext, hasChatId, onRetry }: Props) {
  const mapped = mapError(error);

  return (
    <main className="page auth-page">
      <section className="card page-hero">
        <p className="page-kicker">Who is the Spy</p>
        <h1 className="page-title">Вход в мини-апп</h1>
        <p className="page-subtitle">
          Привязываем сессию к Telegram, чтобы безопасно открыть игровой интерфейс и сохранить ваш прогресс.
        </p>
      </section>

      <section className="card">
        <h2>Проверка окружения</h2>
        {loading ? <p>Проверяем Telegram-сессию...</p> : null}

        {!hasTelegramContext ? (
          <p className="error-text">Откройте приложение из Telegram, чтобы передать initData.</p>
        ) : null}

        {!hasChatId ? (
          <p className="error-text">Не удалось определить chat_id. Откройте Mini App из нужной группы.</p>
        ) : null}

        {error ? (
          <div className="error-block" role="alert">
            <h2>{mapped.title}</h2>
            <p>{mapped.message}</p>
            {mapped.cta ? <p className="hint">{mapped.cta}</p> : null}
          </div>
        ) : null}

        <button type="button" className="button button-primary" onClick={onRetry} disabled={loading} aria-busy={loading}>
          {loading ? "Авторизуем..." : "Повторить авторизацию"}
        </button>
      </section>
    </main>
  );
}
