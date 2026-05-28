import { AuthGatePage } from "../pages/AuthGatePage";
import { GameShellPage } from "../pages/GameShellPage";
import { useMiniAppAuth } from "../hooks/useMiniAppAuth";
import { useTelegramWebApp } from "../hooks/useTelegramWebApp";

export function App() {
  const telegram = useTelegramWebApp();
  const auth = useMiniAppAuth(telegram.initData, telegram.chatId);

  if (!auth.session || auth.status !== "ready") {
    return (
      <AuthGatePage
        loading={auth.status === "loading"}
        error={auth.error}
        hasTelegramContext={Boolean(telegram.webApp)}
        hasChatId={telegram.chatId !== null}
        onRetry={() => void auth.authorize()}
      />
    );
  }

  if (telegram.chatId === null) {
    return (
      <AuthGatePage
        loading={false}
        error={{ code: "game_not_found", message: "chat_id не определен" }}
        hasTelegramContext={Boolean(telegram.webApp)}
        hasChatId={false}
        onRetry={() => void auth.authorize()}
      />
    );
  }

  return (
    <GameShellPage
      chatId={telegram.chatId}
      sessionToken={auth.session.token}
      currentUserId={auth.session.user.user_id}
      onSessionExpired={auth.logout}
    />
  );
}
