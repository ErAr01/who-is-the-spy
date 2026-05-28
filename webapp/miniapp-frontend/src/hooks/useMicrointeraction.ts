import { useMemo } from "react";

export function useMicrointeraction(active: boolean, mode: "pulse" | "highlight" = "highlight") {
  return useMemo(() => {
    if (!active) {
      return "";
    }
    return mode === "pulse" ? "ui-pulse" : "ui-highlight";
  }, [active, mode]);
}
