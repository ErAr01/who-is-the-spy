import { AuthGatePage } from "../pages/AuthGatePage";
import { RulesHelp } from "../components/RulesHelp";
import { GameShellPage } from "../pages/GameShellPage";
import { PrivateTestPairPage } from "../pages/PrivateTestPairPage";
import { useMiniAppAuth } from "../hooks/useMiniAppAuth";
import { useTelegramWebApp } from "../hooks/useTelegramWebApp";

export function App() {
  const telegram = useTelegramWebApp();
  const auth = useMiniAppAuth(telegram.initData, telegram.chatId);
  const isPrivateTestPairMode = telegram.mode === "testpair" || telegram.isPrivateChat;
  const page = !auth.session || auth.status !== "ready"
    ? (
      <AuthGatePage
        loading={auth.status === "loading"}
        error={auth.error}
        hasTelegramContext={Boolean(telegram.webApp)}
        hasChatId={telegram.chatId !== null}
        onRetry={() => void auth.authorize()}
      />
    )
    : telegram.chatId === null
      ? (
        <AuthGatePage
          loading={false}
          error={{ code: "game_not_found", message: "chat_id не определен" }}
          hasTelegramContext={Boolean(telegram.webApp)}
          hasChatId={false}
          onRetry={() => void auth.authorize()}
        />
      )
      : isPrivateTestPairMode
        ? <PrivateTestPairPage sessionToken={auth.session.token} onSessionExpired={auth.logout} />
        : (
          <GameShellPage
            chatId={telegram.chatId}
            sessionToken={auth.session.token}
            currentUserId={auth.session.user.user_id}
            onSessionExpired={auth.logout}
          />
        );
  return (
    <>
      {page}
      <RulesHelp />
    </>
  );
}
