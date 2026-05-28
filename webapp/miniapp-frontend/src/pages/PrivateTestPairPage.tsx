import { useEffect, useState } from "react";

import { mapError } from "../api/errorMap";
import { miniAppClient } from "../api/miniappClient";
import type { ApiError, MiniAppTestPairResponse } from "../api/types";
import { categoryLabel } from "../utils/categoryLabels";

interface Props {
  sessionToken: string;
  onSessionExpired: () => void;
}

export function PrivateTestPairPage({ sessionToken, onSessionExpired }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [pair, setPair] = useState<MiniAppTestPairResponse | null>(null);
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);

  const generate = async () => {
    setPending(true);
    setError(null);
    try {
      const payload = await miniAppClient.getTestPair(sessionToken, selectedCategories);
      setPair(payload);
      setAvailableCategories(payload.available_categories);
      setSelectedCategories(payload.selected_categories);
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

  const toggleCategory = (category: string) => {
    setSelectedCategories((prev) =>
      prev.includes(category) ? prev.filter((item) => item !== category) : [...prev, category].sort()
    );
  };

  useEffect(() => {
    if (pair || pending) {
      return;
    }
    void generate();
  }, [pair, pending]);

  return (
    <main className="page">
      <section className="card page-hero">
        <p className="page-kicker">Режим теста</p>
        <h1 className="page-title">Тестовая пара карточек</h1>
        <p className="page-subtitle">
          Этот режим работает в личке и позволяет быстро проверить пары «мирный/шпион» без запуска полноценного раунда.
        </p>
        <button type="button" className="button button-primary" onClick={() => void generate()} disabled={pending} aria-busy={pending}>
          {pending ? "Генерируем..." : "Сгенерировать пару"}
        </button>
      </section>

      <section className="card">
        <h2>Параметры генерации</h2>
        <p className="muted">Можно зафиксировать категории, чтобы проверять конкретную тематику.</p>
      </section>

      {availableCategories.length ? (
        <section className="card">
          <h2>Категории</h2>
          <p className="muted">Если ничего не выбрано, используются все категории.</p>
          <div className="chip-grid">
            {availableCategories.map((category) => (
              <button
                key={category}
                type="button"
                className={`chip-button ${selectedCategories.includes(category) ? "active" : ""}`}
                onClick={() => toggleCategory(category)}
                disabled={pending}
              >
                {categoryLabel(category)}
              </button>
            ))}
          </div>
        </section>
      ) : null}

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
            {pair.civilian.image_url ? (
              <img className="card-image" src={pair.civilian.image_url} alt={pair.civilian.name} loading="lazy" />
            ) : null}
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
            {pair.spy.image_url ? <img className="card-image" src={pair.spy.image_url} alt={pair.spy.name} loading="lazy" /> : null}
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
