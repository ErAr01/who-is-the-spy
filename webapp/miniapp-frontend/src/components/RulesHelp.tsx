import { useState } from "react";

const RULES_TEXT: string[] = [
  "Каждому игроку показывается картинка с персонажем. У большинства игроков будет один и тот же персонаж, но у одного игрока — другой. Этот игрок и есть шпион.",
  "По очереди игроки называют факты о своём персонаже: как он выглядит, где мог появляться, какие у него особенности, характер или ассоциации. При этом важно говорить так, чтобы не раскрыть слишком много, но и не вызвать подозрений.",
  "Ваша задача — понять, кто вы: мирный житель или шпион. Слушайте ответы других игроков, сравнивайте их со своей картинкой и пытайтесь определить, кто говорит не о том персонаже.",
  "Если вы поняли, что шпион — это вы, старайтесь подстраиваться под ответы остальных игроков, говорить осторожно и не выдавать себя.",
  "В конце раунда все игроки голосуют за того, кого считают шпионом. Побеждают мирные жители, если правильно находят шпиона. Шпион побеждает, если ему удаётся остаться незамеченным."
];

export function RulesHelp() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" className="rules-help-button" onClick={() => setOpen(true)}>
        Как играть?
      </button>
      {open ? (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Правила игры" onClick={() => setOpen(false)}>
          <div className="dialog rules-dialog" onClick={(event) => event.stopPropagation()}>
            <h3>Как играть</h3>
            <div className="rules-dialog-content">
              {RULES_TEXT.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
            <div className="dialog-actions">
              <button type="button" className="button button-primary" onClick={() => setOpen(false)}>
                Понятно
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
