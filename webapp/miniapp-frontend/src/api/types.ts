export type GameState = "lobby" | "custom_setup" | "playing" | "voting" | "finished";
export type ConnectionState = "loading" | "fresh" | "stale" | "reconnecting";

export interface ApiError {
  code: string;
  message: string;
  status?: number;
}

export interface MiniAppUser {
  user_id: number;
  name: string;
}

export interface MiniAppAuthResponse {
  session_token: string;
  expires_at: number;
  user: MiniAppUser;
}

export interface MiniAppPlayer {
  user_id: number;
  name: string;
}

export interface MiniAppSnapshot {
  chat_id: number;
  state: GameState;
  admin_id: number;
  players: MiniAppPlayer[];
  round_player_ids: number[];
  selected_categories: string[];
  available_categories: string[];
  votes_count: number;
  version: number;
  updated_at_ts: number | null;
  is_admin: boolean;
  is_member: boolean;
  is_in_current_round: boolean;
}

export interface MiniAppSnapshotResponse {
  no_change: boolean;
  version: number;
  updated_at_ts: number | null;
  snapshot: MiniAppSnapshot | null;
}

export interface MiniAppActionResponse {
  ok: boolean;
  version: number;
  updated_at_ts: number | null;
  note_code: string | null;
  note_message: string | null;
}

export interface MiniAppRoleResponse {
  has_role: boolean;
  is_spy: boolean | null;
  role_name: string | null;
  payload_type: string | null;
  payload: string | null;
}

export interface MiniAppTestPairCard {
  card_id: string;
  name: string;
  image_url: string | null;
  wiki_url: string | null;
  search_url: string | null;
}

export interface MiniAppTestPairResponse {
  theme: string;
  available_categories: string[];
  selected_categories: string[];
  civilian: MiniAppTestPairCard;
  spy: MiniAppTestPairCard;
}

export interface MappedError {
  title: string;
  message: string;
  cta?: string;
  shouldLogout?: boolean;
}
