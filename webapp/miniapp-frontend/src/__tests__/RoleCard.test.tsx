import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MiniAppRoleResponse } from "../api/types";
import { RoleCard } from "../components/RoleCard";

function makeRole(overrides: Partial<MiniAppRoleResponse> = {}): MiniAppRoleResponse {
  return {
    has_role: true,
    is_spy: false,
    role_name: "Тестовый Герой",
    payload_type: "photo",
    payload: "test-hero",
    image_url: null,
    wiki_url: null,
    search_url: null,
    category: "anime",
    category_label: "Аниме",
    description: "Краткое описание героя.",
    hints_total: 10,
    hints_used: 0,
    ...overrides
  };
}

function makeHints(overrides: Partial<Parameters<typeof RoleCard>[0]["hints"] & object> = {}) {
  return {
    revealed: [],
    loading: false,
    error: null,
    remaining: null,
    total: 0,
    used: 0,
    onRevealHint: vi.fn(),
    ...overrides
  };
}

describe("RoleCard hints", () => {
  it("enables the hint button on a fresh round before the first request (hook total=0 falls back to role)", () => {
    // Регрессия: `hints.total ?? ...` не падал назад на role.hints_total, т.к. 0 не nullish —
    // кнопка была мертва до первого запроса.
    render(<RoleCard role={makeRole()} loading={false} onReveal={vi.fn()} hints={makeHints()} />);

    const button = screen.getByRole("button", { name: "Подсказка 1/10" });
    expect(button).toBeEnabled();
  });

  it("disables the hint button when the card has no facts", () => {
    render(
      <RoleCard
        role={makeRole({ hints_total: 0 })}
        loading={false}
        onReveal={vi.fn()}
        hints={makeHints()}
      />
    );

    const button = screen.getByRole("button", { name: "Подсказок нет" });
    expect(button).toBeDisabled();
  });

  it("disables the hint button when all hints are exhausted", () => {
    render(
      <RoleCard
        role={makeRole()}
        loading={false}
        onReveal={vi.fn()}
        hints={makeHints({ total: 10, used: 10, remaining: 0, revealed: Array(10).fill("факт") })}
      />
    );

    const button = screen.getByRole("button", { name: "Подсказки закончились" });
    expect(button).toBeDisabled();
  });

  it("hides the description button when description is missing", () => {
    render(
      <RoleCard role={makeRole({ description: null })} loading={false} onReveal={vi.fn()} hints={makeHints()} />
    );

    expect(screen.queryByRole("button", { name: "Описание" })).toBeNull();
  });
});
