import { useEffect, useMemo, useState } from "react";

import { mapError } from "../api/errorMap";
import type { ApiError, MiniAppSnapshot } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ToastHost, type Toast } from "../components/ToastHost";
import { TopStatusBar } from "../components/TopStatusBar";
import { useGameActions } from "../hooks/useGameActions";
import { useGamePolling } from "../hooks/useGamePolling";
import { useHaptics } from "../hooks/useHaptics";
import { useRole } from "../hooks/useRole";
import { useRoundRoles } from "../hooks/useRoundRoles";
import { useMicrointeraction } from "../hooks/useMicrointeraction";
import { FinishedScreen } from "../screens/FinishedScreen";
import { LobbyScreen } from "../screens/LobbyScreen";
import { PlayingScreen } from "../screens/PlayingScreen";
import { VotingScreen } from "../screens/VotingScreen";

interface Props {
  chatId: number;
  sessionToken: string;
  currentUserId: number;
  onSessionExpired: () => void;
}

function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = (kind: Toast["kind"], text: string) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { id, kind, text }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 3200);
  };

  return {
    toasts,
    dismiss: (id: string) => setToasts((prev) => prev.filter((item) => item.id !== id)),
    push
  };
}

function screenFromSnapshot(snapshot: MiniAppSnapshot | null): "lobby" | "playing" | "voting" | "finished" {
  if (!snapshot) {
    return "lobby";
  }
  if (snapshot.state === "playing") {
    return "playing";
  }
  if (snapshot.state === "voting") {
    return "voting";
  }
  if (snapshot.state === "finished") {
    return "finished";
  }
  return "lobby";
}

export function GameShellPage({ chatId, sessionToken, currentUserId, onSessionExpired }: Props) {
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const { impact, notify } = useHaptics();
  const { toasts, dismiss, push } = useToasts();

  const polling = useGamePolling(sessionToken, chatId);
  const actions = useGameActions(sessionToken, chatId, polling.refreshNow);
  const role = useRole(sessionToken, chatId, polling.snapshot?.state);
  const roundRoles = useRoundRoles(sessionToken, chatId, polling.snapshot?.state);

  const shellScreen = useMemo(() => screenFromSnapshot(polling.snapshot), [polling.snapshot]);
  const reconnectedClass = useMicrointeraction(polling.connection === "fresh" && polling.error === null, "highlight");

  useEffect(() => {
    if (polling.connection === "reconnecting") {
      push("info", "Пытаемся восстановить соединение...");
    }
  }, [polling.connection]);

  useEffect(() => {
    const combinedError = actions.actionError ?? polling.error ?? role.error ?? roundRoles.error;
    if (!combinedError) {
      return;
    }

    const mapped = mapError(combinedError);
    push("error", `${mapped.title}: ${mapped.message}`);
    notify("error");

    if (mapped.shouldLogout) {
      onSessionExpired();
    }
  }, [actions.actionError, notify, onSessionExpired, polling.error, push, role.error, roundRoles.error]);

  useEffect(() => {
    if (!actions.actionNote) {
      return;
    }
    push("info", actions.actionNote);
  }, [actions.actionNote, push]);

  const renderScreen = () => {
    const snapshot = polling.snapshot;
    if (!snapshot) {
      return (
        <section className="card">
          <h2>Загружаем состояние игры</h2>
          <p className="muted">Ожидаем первый snapshot от сервера.</p>
        </section>
      );
    }

    if (shellScreen === "playing") {
      return (
        <PlayingScreen
          snapshot={snapshot}
          role={role.role}
          roleLoading={role.loading}
          pendingAction={actions.pendingAction}
          onRevealRole={() => {
            impact("soft");
            void role.revealRole();
          }}
          onOpenVoting={() => {
            impact("medium");
            void actions.openVoting();
          }}
          onCancel={() => setShowCancelConfirm(true)}
        />
      );
    }

    if (shellScreen === "voting") {
      return (
        <VotingScreen
          snapshot={snapshot}
          currentUserId={currentUserId}
          pendingAction={actions.pendingAction}
          onVote={(targetId) => {
            impact("light");
            void actions.vote(targetId);
          }}
          onCloseVoting={() => {
            impact("medium");
            void actions.closeVoting();
          }}
        />
      );
    }

    if (shellScreen === "finished") {
      return (
        <FinishedScreen
          snapshot={snapshot}
          role={role.role}
          roleLoading={role.loading}
          roundRoles={roundRoles.roundRoles}
          roundRolesLoading={roundRoles.loading}
          pendingAction={actions.pendingAction}
          onRevealRole={() => {
            impact("soft");
            void role.revealRole();
          }}
          onRevealRoundRoles={() => {
            impact("soft");
            void roundRoles.revealRoundRoles();
          }}
          onCancel={() => setShowCancelConfirm(true)}
        />
      );
    }

    return (
      <LobbyScreen
        snapshot={snapshot}
        pendingAction={actions.pendingAction}
        onJoin={() => {
          impact("light");
          void actions.join();
        }}
        onLeave={() => {
          impact("light");
          void actions.leave();
        }}
        onToggleCategory={(category) => {
          impact("light");
          void actions.toggleCategory(category);
        }}
        onStart={() => {
          impact("medium");
          void actions.start();
        }}
        onCancel={() => setShowCancelConfirm(true)}
      />
    );
  };

  const combinedError: ApiError | null = actions.actionError ?? polling.error ?? role.error ?? roundRoles.error;
  const playersCount = polling.snapshot?.players.length ?? 0;
  const screenSubtitle =
    shellScreen === "lobby"
      ? "Соберите команду, выберите категории и подготовьтесь к старту раунда."
      : shellScreen === "playing"
        ? "Обсуждайте карточки, скрывайте эмоции и вычисляйте шпиона."
        : shellScreen === "voting"
          ? "Выберите подозреваемого и завершите голосование админом."
          : "Раунд завершен: можно обсудить результат и запустить новую игру.";

  return (
    <main className={`page shell-page ${reconnectedClass}`}>
      <section className="card page-hero">
        <p className="page-kicker">Игровой стол</p>
        <h1 className="page-title">Кто шпион?</h1>
        <p className="page-subtitle">{screenSubtitle}</p>
        <div className="chip-grid" aria-label="Сводка игры">
          <span className="chip">Игроков: {playersCount}</span>
          <span className="chip">Ваш ID: {currentUserId}</span>
          <span className="chip">Чат: {chatId}</span>
        </div>
      </section>

      <TopStatusBar gameState={polling.snapshot?.state ?? null} connection={polling.connection} />

      {combinedError ? (
        <section className="card error-block" role="alert">
          <h2>{mapError(combinedError).title}</h2>
          <p>{mapError(combinedError).message}</p>
          {mapError(combinedError).cta ? <p className="hint">{mapError(combinedError).cta}</p> : null}
        </section>
      ) : null}

      {renderScreen()}

      <ConfirmDialog
        open={showCancelConfirm}
        title="Сбросить текущую игру?"
        description="Это действие завершит текущий игровой цикл для всех участников."
        confirmText="Сбросить"
        onCancel={() => setShowCancelConfirm(false)}
        onConfirm={() => {
          setShowCancelConfirm(false);
          void actions.cancel();
        }}
      />

      <ToastHost toasts={toasts} onDismiss={dismiss} />
    </main>
  );
}
