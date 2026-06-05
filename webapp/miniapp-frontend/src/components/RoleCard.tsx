import { useEffect, useState } from "react";

import type { ApiError, MiniAppRoleResponse } from "../api/types";

interface HintProps {
  revealed: string[];
  loading: boolean;
  error: ApiError | null;
  remaining: number | null;
  total: number;
  used: number;
  onRevealHint: () => void;
}

interface Props {
  role: MiniAppRoleResponse | null;
  loading: boolean;
  onReveal: () => void;
  hiddenReason?: string;
  hints?: HintProps;
}

export function RoleCard({ role, loading, onReveal, hiddenReason, hints }: Props) {
  const roleTitle = role?.role_name ?? (role?.is_spy ? "Шпион" : "Мирный");
  const alreadyRevealed = Boolean(role?.has_role);
  const revealDisabled = loading || alreadyRevealed;

  // Описание держим за намеренным действием — как и саму роль, чтобы сосед мельком не прочитал.
  const [descriptionShown, setDescriptionShown] = useState(false);

  // Прячем описание снова, когда роль скрывается (новый раунд / смена карточки).
  useEffect(() => {
    if (!role?.has_role) {
      setDescriptionShown(false);
    }
  }, [role?.has_role, role?.payload]);

  const hasDescription = Boolean(role?.description && role.description.trim());
  // До первого запроса хук отдаёт total=0 — это «ещё не знаем», а не «фактов нет»,
  // поэтому используем || (не ??), чтобы упасть назад на данные из /me/role.
  const hintsTotal = hints?.total || role?.hints_total || 0;
  // remaining известен после первого запроса; до него опираемся на total - used из роли.
  const hintsRemaining =
    hints?.remaining ?? Math.max(0, hintsTotal - (role?.hints_used ?? 0));
  const hintCount = hints?.revealed.length ?? 0;
  const hintLoading = hints?.loading ?? false;
  const hintsExhausted = hintsTotal === 0 || hintsRemaining <= 0;
  const hintError = hints?.error ?? null;

  return (
    <section className="card role-card">
      <h2>Твой персонаж</h2>
      {!role?.has_role ? (
        <div>
          <p className="muted">Роль скрыта до старта раунда.</p>
          {hiddenReason ? <p className="hint">{hiddenReason}</p> : null}
        </div>
      ) : (
        <div>
          <p className="role-name">{roleTitle}</p>
          {role.image_url ? <img className="card-image" src={role.image_url} alt={roleTitle} loading="lazy" /> : null}

          {hasDescription ? (
            <div className="role-extra">
              <button
                type="button"
                className="button button-secondary"
                aria-expanded={descriptionShown}
                aria-controls="role-description"
                onClick={() => setDescriptionShown((prev) => !prev)}
              >
                {descriptionShown ? "Скрыть описание" : "Описание"}
              </button>
              {descriptionShown ? (
                <p id="role-description" className="role-description">
                  {role.description}
                </p>
              ) : null}
            </div>
          ) : null}

          {hints ? (
            <div className="role-extra">
              <button
                type="button"
                className="button button-secondary"
                onClick={hints.onRevealHint}
                disabled={hintLoading || hintsExhausted}
                aria-busy={hintLoading}
              >
                {hintLoading
                  ? "Загружаем..."
                  : hintsTotal === 0
                    ? "Подсказок нет"
                    : hintsExhausted
                      ? "Подсказки закончились"
                      : `Подсказка ${Math.min(hintCount + 1, hintsTotal)}/${hintsTotal}`}
              </button>
              {hintError && hintError.code === "hint_forbidden_state" ? (
                <p className="hint error-text">Раунд завершился — подсказки больше недоступны.</p>
              ) : null}
              {hintCount > 0 ? (
                <ol className="hint-list" aria-label="Открытые подсказки">
                  {hints.revealed.map((text, index) => (
                    <li key={`${index}-${text}`} className="hint-list-item">
                      {text}
                    </li>
                  ))}
                </ol>
              ) : null}
            </div>
          ) : null}

          <div className="actions-col">
            {role.wiki_url ? (
              <a className="button button-secondary" href={role.wiki_url} target="_blank" rel="noreferrer">
                Wikipedia
              </a>
            ) : null}
            {role.search_url ? (
              <a className="button button-secondary" href={role.search_url} target="_blank" rel="noreferrer">
                Искать в Google
              </a>
            ) : null}
          </div>
        </div>
      )}
      <button type="button" className="button button-secondary" onClick={onReveal} disabled={revealDisabled}>
        {loading ? "Загружаем..." : alreadyRevealed ? "Персонаж показан" : "Показать роль"}
      </button>
    </section>
  );
}
