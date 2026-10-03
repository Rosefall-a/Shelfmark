import type { CardSet, CardSetDetail } from "../types/set";
import type { BackendCard } from "./cards";
import { mapBackendCard } from "./cards";

interface BackendSet {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  target_total: number | null;
  created_at: number;
  updated_at: number;
  card_count: number;
  is_complete: boolean;
}

interface BackendSetDetail extends BackendSet {
  cards: BackendCard[];
}

function toIso(seconds: number): string {
  return new Date(seconds * 1000).toISOString();
}

function mapBackendSet(raw: BackendSet): CardSet {
  return {
    id: raw.id,
    name: raw.name,
    description: raw.description,
    targetTotal: raw.target_total,
    cardCount: raw.card_count,
    isComplete: raw.is_complete,
    createdAt: toIso(raw.created_at),
    updatedAt: toIso(raw.updated_at),
  };
}

function mapBackendSetDetail(raw: BackendSetDetail): CardSetDetail {
  return {
    ...mapBackendSet(raw),
    cards: raw.cards.map(mapBackendCard),
  };
}

async function handle<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`Failed to ${action}: ${response.status} ${message}`);
  }
  return response.json();
}

export async function fetchSets(): Promise<CardSet[]> {
  const response = await fetch("/api/sets", { credentials: "include" });
  const raw = await handle<BackendSet[]>(response, "fetch sets");
  return raw.map(mapBackendSet);
}

export async function fetchSet(id: string): Promise<CardSetDetail> {
  const response = await fetch(`/api/sets/${id}`, { credentials: "include" });
  const raw = await handle<BackendSetDetail>(response, `fetch set ${id}`);
  return mapBackendSetDetail(raw);
}

export async function createSet(input: {
  name: string;
  description?: string | null;
  targetTotal?: number | null;
}): Promise<CardSet> {
  const response = await fetch("/api/sets", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      description: input.description ?? null,
      target_total: input.targetTotal ?? null,
    }),
  });
  const raw = await handle<BackendSet>(response, "create set");
  return mapBackendSet(raw);
}

export async function updateSet(
  id: string,
  input: {
    name?: string;
    description?: string | null;
    targetTotal?: number | null;
  },
): Promise<CardSet> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.description !== undefined) body.description = input.description;
  if (input.targetTotal !== undefined) body.target_total = input.targetTotal;

  const response = await fetch(`/api/sets/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const raw = await handle<BackendSet>(response, `update set ${id}`);
  return mapBackendSet(raw);
}

export async function deleteSet(id: string): Promise<void> {
  const response = await fetch(`/api/sets/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to delete set ${id}: ${response.status}`);
  }
}
