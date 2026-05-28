import { useState } from "react";

import { mapError } from "../api/errorMap";
import { miniAppClient } from "../api/miniappClient";
import type { ApiError, MiniAppTestPairResponse } from "../api/types";

interface Props {
  sessionToken: string;
  onSessionExpired: () => void;
}

export function PrivateTestPairPage({ sessionToken, onSessionExpired }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [pair, setPair] = useState<MiniAppTestPairResponse | null>(null);

  const generate = async () => {
    setPending(true);
    setError(null);
    try {
      const payload = await miniAppClient.getTestPair(sessionToken);
      setPair(payload);
    } catch (requestError) {
      const apiError = requestError as ApiError;
      setError(apiError);
      if (mapError(apiError).shouldLogout) {
        onSessionExpired();
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="page">
      <section className="card">
        <h1>Тестовая пара карточек</h1>
        <p className="muted">
          Этот режим работает в личке и позволяет быстро проверить пары «мирный/шпион» без запуска полноценного раунда.
        </p>
        <button type="button" className="button button-primary" onClick={() => void generate()} disabled={pending}>
          {pending ? "Генерируем..." : "Сгенерировать пару"}
        </button>
      </section>

      {error ? (
        <section className="card error-block" role="alert">
          <h2>{mapError(error).title}</h2>
          <p>{mapError(error).message}</p>
          {mapError(error).cta ? <p className="hint">{mapError(error).cta}</p> : null}
        </section>
      ) : null}

      {pair ? (
        <>
          <section className="card">
            <h2>Тема</h2>
            <p>{pair.theme}</p>
          </section>

          <section className="card">
            <h2>Мирный</h2>
            <p>
              <strong>{pair.civilian.name}</strong> ({pair.civilian.card_id})
            </p>
            <div className="actions-col">
              {pair.civilian.wiki_url ? (
                <a className="button button-secondary" href={pair.civilian.wiki_url} target="_blank" rel="noreferrer">
                  Wikipedia
                </a>
              ) : null}
              {pair.civilian.search_url ? (
                <a className="button button-secondary" href={pair.civilian.search_url} target="_blank" rel="noreferrer">
                  Google
                </a>
              ) : null}
            </div>
          </section>

          <section className="card">
            <h2>Шпион</h2>
            <p>
              <strong>{pair.spy.name}</strong> ({pair.spy.card_id})
            </p>
            <div className="actions-col">
              {pair.spy.wiki_url ? (
                <a className="button button-secondary" href={pair.spy.wiki_url} target="_blank" rel="noreferrer">
                  Wikipedia
                </a>
              ) : null}
              {pair.spy.search_url ? (
                <a className="button button-secondary" href={pair.spy.search_url} target="_blank" rel="noreferrer">
                  Google
                </a>
              ) : null}
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
