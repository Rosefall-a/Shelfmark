// Bounties, personal goals and challenges. Independent from
// Achievements/Mastery/Cards/Prestige, but a bounty may optionally target
// a game, a specific achievement, or a named collection to compute its
// own progress automatically.

export type BountyType =
  | "completion"
  | "mastery"
  | "achievement"
  | "collection"
  | "challenge"
  | "watch"
  | "custom";
export type BountyDifficulty = "easy" | "normal" | "hard" | "extreme";
export type BountyStatus =
  "not_started" | "active" | "paused" | "completed" | "abandoned";
export type BountyProgressMode = "binary" | "percentage" | "numeric";
export type ObjectiveKind = "checkbox" | "numeric" | "achievement";
export type EvidenceKind = "screenshot" | "clip" | "document" | "note" | "link";

export interface BountyObjective {
  id: string;
  title: string;
  kind: ObjectiveKind;
  done: boolean;
  progress_value: number;
  progress_target: number | null;
  target_achievement_provider: string | null;
  target_achievement_external_id: string | null;
  created_at: number;
}

export interface BountyEvidence {
  id: string;
  kind: EvidenceKind;
  media_item_id: string | null;
  media_url: string | null;
  media_filename: string | null;
  text: string | null;
  url: string | null;
  created_at: number;
}

export interface BountyJournalEntry {
  id: string;
  text: string;
  created_at: number;
}

export interface BountyProposal {
  title: string;
  type: BountyType;
  game_id: string;
  game_title: string | null;
  points_reward: number;
}

export interface Bounty {
  id: string;
  title: string;
  description: string | null;
  type: BountyType;
  difficulty: BountyDifficulty | null;
  status: BountyStatus;
  auto_generated: boolean;
  game_id: string | null;
  game_title: string | null;
  target_achievement_provider: string | null;
  target_achievement_external_id: string | null;
  target_achievement_name: string | null;
  target_collection_name: string | null;
  progress_mode: BountyProgressMode;
  progress_value: number;
  progress_target: number | null;
  points_reward: number;
  required_evidence_kinds: EvidenceKind[];
  target_date: number | null;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  objectives: BountyObjective[];
  evidence: BountyEvidence[];
  journal: BountyJournalEntry[];
}

export interface PointTransaction {
  id: string;
  bounty_id: string;
  amount: number;
  reason: string;
  created_at: number;
}

export interface BountyCreateInput {
  title: string;
  description?: string | null;
  type: BountyType;
  difficulty?: BountyDifficulty | null;
  status?: BountyStatus;
  game_id?: string | null;
  target_achievement_id?: string | null;
  target_collection_name?: string | null;
  progress_mode?: BountyProgressMode;
  progress_target?: number | null;
  points_reward?: number;
  target_date?: number | null;
  required_evidence_kinds?: EvidenceKind[];
}

export interface BountyUpdateInput {
  title?: string;
  description?: string | null;
  difficulty?: BountyDifficulty | null;
  points_reward?: number;
  target_date?: number | null;
  progress_value?: number;
  progress_target?: number | null;
  required_evidence_kinds?: EvidenceKind[];
}

export interface ObjectiveCreateInput {
  title: string;
  kind: ObjectiveKind;
  progress_target?: number | null;
  target_achievement_id?: string | null;
}

export interface ObjectiveUpdateInput {
  title?: string;
  done?: boolean;
  progress_value?: number;
  progress_target?: number | null;
}

export interface EvidenceCreateInput {
  kind: EvidenceKind;
  media_item_id?: string | null;
  text?: string | null;
  url?: string | null;
}

async function handle<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      body?.detail ||
        `Failed to ${action}: ${response.status} ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchBounties(filters?: {
  status?: BountyStatus;
  type?: BountyType;
}): Promise<Bounty[]> {
  if (import.meta.env.VITE_USE_MOCK_DATA === "true") return [];
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.type) params.set("type", filters.type);
  const query = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`/api/bounties${query}`, {
    credentials: "include",
  });
  const body = await handle<{ bounties: Bounty[] }>(response, "fetch bounties");
  return body.bounties;
}

export async function fetchBounty(id: string): Promise<Bounty> {
  const response = await fetch(`/api/bounties/${id}`, {
    credentials: "include",
  });
  const body = await handle<{ bounty: Bounty }>(response, "fetch bounty");
  return body.bounty;
}

export async function createBounty(input: BountyCreateInput): Promise<Bounty> {
  const response = await fetch("/api/bounties", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = await handle<{ bounty: Bounty }>(response, "create bounty");
  return body.bounty;
}

export async function updateBounty(
  id: string,
  input: BountyUpdateInput,
): Promise<Bounty> {
  const response = await fetch(`/api/bounties/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = await handle<{ bounty: Bounty }>(response, "update bounty");
  return body.bounty;
}

export async function completeBounty(id: string): Promise<void> {
  await handle(
    await fetch(`/api/bounties/${id}/complete`, {
      method: "POST",
      credentials: "include",
    }),
    "complete bounty",
  );
}

export async function pauseBounty(id: string): Promise<void> {
  await handle(
    await fetch(`/api/bounties/${id}/pause`, {
      method: "POST",
      credentials: "include",
    }),
    "pause bounty",
  );
}

export async function resumeBounty(id: string): Promise<void> {
  await handle(
    await fetch(`/api/bounties/${id}/resume`, {
      method: "POST",
      credentials: "include",
    }),
    "resume bounty",
  );
}

export async function abandonBounty(id: string): Promise<void> {
  await handle(
    await fetch(`/api/bounties/${id}/abandon`, {
      method: "POST",
      credentials: "include",
    }),
    "abandon bounty",
  );
}

export async function deleteBounty(id: string): Promise<void> {
  await handle(
    await fetch(`/api/bounties/${id}`, {
      method: "DELETE",
      credentials: "include",
    }),
    "delete bounty",
  );
}

export async function fetchPointsTotal(): Promise<number> {
  const response = await fetch("/api/bounties/points/total", {
    credentials: "include",
  });
  const body = await handle<{ total: number }>(response, "fetch points total");
  return body.total;
}

export async function fetchPointsHistory(): Promise<PointTransaction[]> {
  const response = await fetch("/api/bounties/points/history", {
    credentials: "include",
  });
  const body = await handle<{ transactions: PointTransaction[] }>(
    response,
    "fetch points history",
  );
  return body.transactions;
}

export async function createObjective(
  bountyId: string,
  input: ObjectiveCreateInput,
): Promise<Bounty> {
  const response = await fetch(`/api/bounties/${bountyId}/objectives`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = await handle<{ bounty: Bounty }>(response, "create objective");
  return body.bounty;
}

export async function updateObjective(
  bountyId: string,
  objectiveId: string,
  input: ObjectiveUpdateInput,
): Promise<Bounty> {
  const response = await fetch(
    `/api/bounties/${bountyId}/objectives/${objectiveId}`,
    {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  const body = await handle<{ bounty: Bounty }>(response, "update objective");
  return body.bounty;
}

export async function deleteObjective(
  bountyId: string,
  objectiveId: string,
): Promise<void> {
  await handle(
    await fetch(`/api/bounties/${bountyId}/objectives/${objectiveId}`, {
      method: "DELETE",
      credentials: "include",
    }),
    "delete objective",
  );
}

export async function createEvidence(
  bountyId: string,
  input: EvidenceCreateInput,
): Promise<BountyEvidence> {
  const response = await fetch(`/api/bounties/${bountyId}/evidence`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = await handle<{ evidence: BountyEvidence }>(
    response,
    "create evidence",
  );
  return body.evidence;
}

export async function deleteEvidence(
  bountyId: string,
  evidenceId: string,
): Promise<void> {
  await handle(
    await fetch(`/api/bounties/${bountyId}/evidence/${evidenceId}`, {
      method: "DELETE",
      credentials: "include",
    }),
    "delete evidence",
  );
}

export async function createJournalEntry(
  bountyId: string,
  text: string,
): Promise<BountyJournalEntry> {
  const response = await fetch(`/api/bounties/${bountyId}/journal`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const body = await handle<{ entry: BountyJournalEntry }>(
    response,
    "add journal entry",
  );
  return body.entry;
}

export async function deleteJournalEntry(
  bountyId: string,
  entryId: string,
): Promise<void> {
  await handle(
    await fetch(`/api/bounties/${bountyId}/journal/${entryId}`, {
      method: "DELETE",
      credentials: "include",
    }),
    "delete journal entry",
  );
}

export async function fetchRandomBountyProposal(): Promise<BountyProposal | null> {
  const response = await fetch("/api/bounties/random", {
    credentials: "include",
  });
  const body = await handle<{ proposal: BountyProposal | null }>(
    response,
    "fetch random bounty",
  );
  return body.proposal;
}
