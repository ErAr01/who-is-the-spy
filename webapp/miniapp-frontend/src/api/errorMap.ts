import type { ApiError, MappedError } from "./types";

const MAP: Record<string, MappedError> = {
  game_not_found: {
    title: "Игра не найдена",
    message: "Похоже, игра уже завершена или чат недоступен.",
    cta: "Обновите экран или откройте игру заново в Telegram."
  },
  member_required: {
    title: "Нужно присоединиться",
    message: "Действие доступно только участникам текущей игры.",
    cta: "Нажмите «Присоединиться к игре» в лобби."
  },
  admin_required: {
    title: "Только для админа",
    message: "Этим действием управляет администратор игры.",
    cta: "Попросите админа выполнить действие."
  },
  private_start_required: {
    title: "Сначала /start в личке",
    message: "Боту нужно разрешение на личные сообщения.",
    cta: "Откройте чат с ботом и отправьте команду /start."
  },
  session_invalid: {
    title: "Сессия истекла",
    message: "Нужно авторизоваться заново через Telegram.",
    cta: "Перезагрузите Mini App.",
    shouldLogout: true
  },
  init_data_expired: {
    title: "initData истек",
    message: "Telegram подпись устарела.",
    cta: "Закройте и заново откройте Mini App.",
    shouldLogout: true
  },
  lobby_reset_due_inactivity: {
    title: "Лобби сброшено",
    message: "Игра была неактивна больше часа, поэтому состав очищен.",
    cta: "Игрокам нужно снова нажать Join."
  },
  private_mode_only: {
    title: "Только личный режим",
    message: "Этот сценарий доступен только в личном чате с ботом.",
    cta: "Откройте Mini App через команду /app в личке."
  },
  testpair_unavailable: {
    title: "Не удалось подобрать пару",
    message: "Для выбранных данных не хватает подходящих карточек.",
    cta: "Попробуйте позже или добавьте больше размеченных карточек."
  }
};

export const FALLBACK_ERROR: MappedError = {
  title: "Что-то пошло не так",
  message: "Не удалось выполнить действие. Попробуйте еще раз.",
  cta: "Если ошибка повторяется, перезапустите Mini App."
};

export function mapError(error: ApiError | null | undefined): MappedError {
  if (!error) {
    return FALLBACK_ERROR;
  }
  return MAP[error.code] ?? {
    title: FALLBACK_ERROR.title,
    message: error.message || FALLBACK_ERROR.message,
    cta: FALLBACK_ERROR.cta
  };
}
