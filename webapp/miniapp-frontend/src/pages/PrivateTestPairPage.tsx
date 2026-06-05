import { useEffect, useState } from "react";

import { mapError } from "../api/errorMap";
import { miniAppClient } from "../api/miniappClient";
import type { ApiError, MiniAppTestPairCard, MiniAppTestPairResponse } from "../api/types";
import { categoryLabel } from "../utils/categoryLabels";

interface Props {
  sessionToken: string;
  onSessionExpired: () => void;
}

function TestCardContent({ card }: { card: MiniAppTestPairCard }) {
  const facts = card.facts ?? [];
  return (
    <>
      {card.image_url ? (
        <img className="card-image" src={card.image_url} alt={card.name} loading="lazy" />
      ) : null}
      <p>
        <strong>{card.name}</strong> ({card.card_id})
      </p>
      {card.description ? (
        <p className="role-description">{card.description}</p>
      ) : (
        <p className="muted">Описание ещё не сгенерировано.</p>
      )}
      {facts.length ? (
        <details className="facts-details">
          <summary>Факты ({facts.length})</summary>
          <ol className="hint-list">
            {facts.map((fact, index) => (
              <li key={`${index}-${fact}`} className="hint-list-item">
                {fact}
              </li>
            ))}
          </ol>
        </details>
      ) : (
        <p className="muted">Факты ещё не сгенерированы.</p>
      )}
      <div className="actions-col">
        {card.wiki_url ? (
          <a className="button button-secondary" href={card.wiki_url} target="_blank" rel="noreferrer">
            Wikipedia
          </a>
        ) : null}
        {card.search_url ? (
          <a className="button button-secondary" href={card.search_url} target="_blank" rel="noreferrer">
            Google
          </a>
        ) : null}
      </div>
    </>
  );
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
            <TestCardContent card={pair.civilian} />
          </section>

          <section className="card">
            <h2>Шпион</h2>
            <TestCardContent card={pair.spy} />
          </section>
        </>
      ) : null}
    </main>
  );
}
