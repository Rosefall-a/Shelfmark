import type { Card, CardRarity, CardStatus } from "../types/card";
import type { CardCustomization } from "../types/card";

// The exact shape FastAPI sends, snake_case, matching the Python model
// field-for-field.
export interface BackendCard {
  id: string;
  user_id: string;
  game_id: string;
  archive_number: number | null;
  set_id: string | null;
  rarity: CardRarity | null;
  bounty_id: string | null;
  card_customization: CardCustomization | null;
  status: CardStatus;
  created_at: number;
  updated_at: number;
}

function toIso(seconds: number): string {
  return new Date(seconds * 1000).toISOString();
}

export function mapBackendCard(raw: BackendCard): Card {
  return {
    id: raw.id,
    gameId: raw.game_id,
    archiveNumber: raw.archive_number,
    setId: raw.set_id,
    rarity: raw.rarity,
    bountyId: raw.bounty_id,
    cardCustomization: raw.card_customization,
    status: raw.status,
    createdAt: toIso(raw.created_at),
    updatedAt: toIso(raw.updated_at),
  };
}

async function handle<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`Failed to ${action}: ${response.status} ${message}`);
  }
  return response.json();
}

export async function listCards(filters?: {
  gameId?: string;
  setId?: string;
}): Promise<Card[]> {
  const params = new URLSearchParams();
  if (filters?.gameId) params.set("game_id", filters.gameId);
  if (filters?.setId) params.set("set_id", filters.setId);
  const query = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`/api/cards${query}`, {
    credentials: "include",
  });
  const raw = await handle<BackendCard[]>(response, "list cards");
  return raw.map(mapBackendCard);
}

export async function listCardsForGame(gameId: string): Promise<Card[]> {
  return listCards({ gameId });
}

export async function getCard(id: string): Promise<Card> {
  const response = await fetch(`/api/cards/${id}`, { credentials: "include" });
  const raw = await handle<BackendCard>(response, `fetch card ${id}`);
  return mapBackendCard(raw);
}

export interface CardCreateInput {
  gameId: string;
  setId?: string | null;
  rarity?: CardRarity | null;
  cardCustomization?: CardCustomization | null;
}

export async function createCard(input: CardCreateInput): Promise<Card> {
  const response = await fetch("/api/cards", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      game_id: input.gameId,
      set_id: input.setId ?? null,
      rarity: input.rarity ?? null,
      card_customization: input.cardCustomization ?? null,
    }),
  });
  const raw = await handle<BackendCard>(response, "create card");
  return mapBackendCard(raw);
}

// A lean, partial update — only the keys present in `fields` are sent,
// matching the backend's exclude_unset PATCH semantics.
export interface CardFieldUpdate {
  setId?: string | null;
  rarity?: CardRarity | null;
  cardCustomization?: CardCustomization | null;
  status?: CardStatus;
}

export async function updateCard(
  id: string,
  fields: CardFieldUpdate,
): Promise<Card> {
  const body: Record<string, unknown> = {};
  if ("setId" in fields) body.set_id = fields.setId;
  if ("rarity" in fields) body.rarity = fields.rarity;
  if ("cardCustomization" in fields)
    body.card_customization = fields.cardCustomization;
  if ("status" in fields) body.status = fields.status;

  const response = await fetch(`/api/cards/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const raw = await handle<BackendCard>(response, `update card ${id}`);
  return mapBackendCard(raw);
}

// Auto-generates the one Prestige challenge for this card as a real
// Bounty and links it — see backend features/cards/prestige_challenge.py.
// Takes no input: the challenge is entirely system-picked from the
// game's own data.
export async function generatePrestigeChallenge(id: string): Promise<Card> {
  const response = await fetch(`/api/cards/${id}/prestige-challenge`, {
    method: "POST",
    credentials: "include",
  });
  const raw = await handle<BackendCard>(
    response,
    `generate prestige challenge for card ${id}`,
  );
  return mapBackendCard(raw);
}

export async function deleteCard(id: string): Promise<void> {
  const response = await fetch(`/api/cards/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to delete card ${id}: ${response.status}`);
  }
}
