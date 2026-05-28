import type {
  ApiError,
  MiniAppActionResponse,
  MiniAppAuthResponse,
  MiniAppRoleResponse,
  MiniAppSnapshotResponse,
  MiniAppTestPairResponse
} from "./types";

export class MiniAppApiClient {
  constructor(private readonly baseUrl: string) {}

  async auth(initData: string, chatId: number): Promise<MiniAppAuthResponse> {
    return this.request<MiniAppAuthResponse>("/auth", {
      method: "POST",
      body: JSON.stringify({ init_data: initData, chat_id: chatId })
    });
  }

  async getGame(sessionToken: string, chatId: number, sinceVersion?: number): Promise<MiniAppSnapshotResponse> {
    const params = new URLSearchParams({ chat_id: String(chatId) });
    if (sinceVersion !== undefined) {
      params.set("since_version", String(sinceVersion));
    }
    return this.request<MiniAppSnapshotResponse>(`/game?${params.toString()}`, {
      method: "GET",
      sessionToken
    });
  }

  async getRole(sessionToken: string, chatId: number): Promise<MiniAppRoleResponse> {
    const params = new URLSearchParams({ chat_id: String(chatId) });
    return this.request<MiniAppRoleResponse>(`/me/role?${params.toString()}`, { method: "GET", sessionToken });
  }

  async join(sessionToken: string, chatId: number): Promise<MiniAppActionResponse> {
    return this.action("/join", sessionToken, chatId);
  }

  async toggleCategory(sessionToken: string, chatId: number, category: string): Promise<MiniAppActionResponse> {
    return this.request<MiniAppActionResponse>("/categories/toggle", {
      method: "POST",
      sessionToken,
      body: JSON.stringify({ chat_id: chatId, category })
    });
  }

  async start(sessionToken: string, chatId: number): Promise<MiniAppActionResponse> {
    return this.action("/start", sessionToken, chatId);
  }

  async openVoting(sessionToken: string, chatId: number): Promise<MiniAppActionResponse> {
    return this.action("/voting/open", sessionToken, chatId);
  }

  async vote(sessionToken: string, chatId: number, targetId: number): Promise<MiniAppActionResponse> {
    return this.request<MiniAppActionResponse>("/votes", {
      method: "POST",
      sessionToken,
      body: JSON.stringify({ chat_id: chatId, target_id: targetId })
    });
  }

  async closeVoting(sessionToken: string, chatId: number): Promise<MiniAppActionResponse> {
    return this.action("/voting/close", sessionToken, chatId);
  }

  async cancel(sessionToken: string, chatId: number): Promise<MiniAppActionResponse> {
    return this.action("/cancel", sessionToken, chatId);
  }

  async getTestPair(sessionToken: string, categories?: string[]): Promise<MiniAppTestPairResponse> {
    const params = new URLSearchParams();
    for (const category of categories ?? []) {
      params.append("categories", category);
    }
    const suffix = params.toString();
    return this.request<MiniAppTestPairResponse>(`/testpair${suffix ? `?${suffix}` : ""}`, {
      method: "GET",
      sessionToken
    });
  }

  private action(path: string, sessionToken: string, chatId: number): Promise<MiniAppActionResponse> {
    return this.request<MiniAppActionResponse>(path, {
      method: "POST",
      sessionToken,
      body: JSON.stringify({ chat_id: chatId })
    });
  }

  private async request<T>(
    path: string,
    options: { method: "GET" | "POST"; body?: string; sessionToken?: string }
  ): Promise<T> {
    const response = await fetch(`${this.baseUrl}/api/v1/miniapp${path}`, {
      method: options.method,
      headers: {
        "Content-Type": "application/json",
        ...(options.sessionToken ? { Authorization: `Bearer ${options.sessionToken}` } : {})
      },
      body: options.body
    });

    if (!response.ok) {
      let parsed: ApiError = { code: "unknown_error", message: `HTTP ${response.status}`, status: response.status };
      try {
        const payload = (await response.json()) as { error?: { code?: string; message?: string } };
        parsed = {
          code: payload.error?.code ?? "unknown_error",
          message: payload.error?.message ?? parsed.message,
          status: response.status
        };
      } catch {
        // Keep fallback parsed error.
      }
      throw parsed;
    }

    return (await response.json()) as T;
  }
}

const apiBase = import.meta.env.VITE_MINIAPP_API_BASE ?? "";

export const miniAppClient = new MiniAppApiClient(apiBase);
