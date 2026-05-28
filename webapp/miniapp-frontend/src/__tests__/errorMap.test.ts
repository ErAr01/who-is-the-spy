import { describe, expect, it } from "vitest";

import { FALLBACK_ERROR, mapError } from "../api/errorMap";

describe("mapError", () => {
  it("returns predefined mapping for known code", () => {
    const result = mapError({ code: "admin_required", message: "x" });
    expect(result.title).toBe("Только для админа");
  });

  it("uses fallback for unknown code", () => {
    const result = mapError({ code: "other", message: "Сырой текст" });
    expect(result.title).toBe(FALLBACK_ERROR.title);
    expect(result.message).toBe("Сырой текст");
  });
});
