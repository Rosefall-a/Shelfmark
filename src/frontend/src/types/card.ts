// A Collector Card is its own entity (see database/models/card.py) —
// separate from Game, since a game can eventually carry more than one card
// for genuinely different accomplishments (a normal 100% completion vs. a
// separate Prestige challenge run), each with its own permanent
// archiveNumber. rarity is picked by hand; prestige is never a manual
// field — bountyId links to a system-auto-generated Bounty (see
// services/cards.ts's generatePrestigeChallenge), and whether the card is
// actually prestiged is derived from that bounty's status, never stored
// here.
export type CardRarity =
  "common" | "uncommon" | "rare" | "legendary" | "mythic";
export type CardStatus = "draft" | "approved" | "printed" | "archived";

export interface Card {
  id: string;
  gameId: string;
  archiveNumber: number | null;
  setId: string | null;
  rarity: CardRarity | null;
  bountyId: string | null;
  cardCustomization: CardCustomization | null;
  status: CardStatus;
  createdAt: string;
  updatedAt: string;
}

// Everything a user can pick on the Collector Card designer that isn't
// derived from real game data. Stored as one JSONB blob on the backend
// (cards.card_customization) so a new customization knob is a
// frontend-only change, never a migration.

export type CardFrontTemplate =
  "classic" | "borderless" | "ornate" | "minimal" | "bordered";
export type CardBackTemplate = "emblem" | "collector" | "record";
export type CardAccent = "gold" | "silver" | "bronze" | "copper" | "rose";
export type CardBorderColor = "black" | "white" | "accent";
export type CardFace = "dark" | "parchment";
export type CardTitlePosition = "top" | "bottom";
export type PrestigeVariant = "foil" | "engraved" | "ceremonial" | "minimal";

export interface CardCustomization {
  frontTemplate: CardFrontTemplate;
  backTemplate: CardBackTemplate;
  titlePosition: CardTitlePosition;
  accent: CardAccent;
  borderColor: CardBorderColor;
  cardFace: CardFace;
  prestigeVariant: PrestigeVariant;
  // primary symbol (type line, collector line, back medallion)
  symbol: string;
  // optional second symbol, combined as a small badge on the back
  // medallion only — 'none' means no badge
  symbol2: string;
  // tilts the primary symbol wherever it's shown, degrees
  symbolRotation: number;
  // a data: URI of an uploaded image, overrides the built-in symbol (and
  // its rotation) everywhere it appears when set
  customSymbol: string | null;
  // a data: URI overriding the game's own cover art for this card
  // specifically — null means use the game's real cover image
  customArt: string | null;
  // the achievement you actually want remembered, not just whichever one
  // unlocked last — free text since it's about which one mattered, not a
  // lookup into the game's real achievement list
  memorableAchievement: string;
  // a short personal note for the back, why this one mattered — distinct
  // from Game.notes (that's general library notes, this is the card's own)
  personalNote: string;
}

export const DEFAULT_CARD_CUSTOMIZATION: CardCustomization = {
  frontTemplate: "classic",
  backTemplate: "emblem",
  titlePosition: "top",
  accent: "gold",
  borderColor: "black",
  cardFace: "dark",
  prestigeVariant: "foil",
  symbol: "star",
  symbol2: "none",
  symbolRotation: 0,
  customSymbol: null,
  customArt: null,
  memorableAchievement: "",
  personalNote: "",
};

// The full icon library — pick one for the type line and collector line,
// optionally combine a second as a small badge on the back medallion, or
// upload a custom image to override both. Each value is the inner content
// of a `<svg viewBox="0 0 24 24" fill="currentColor">`.
export const CARD_SYMBOLS: Record<string, string> = {
  star: '<path d="M12 2l3.5 8.5L22 12l-6.5 1.5L12 22l-3.5-8.5L2 12l6.5-1.5z"/>',
  diamond: '<path d="M12 2l7 9-7 11-7-11z"/>',
  hex: '<path d="M12 2l8 5v10l-8 5-8-5V7z"/>',
  compass:
    '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M15 9l-2 6-6 2 2-6z"/>',
  shield:
    '<path d="M12 2l8 3.5v6c0 5-3.4 8.4-8 10.5-4.6-2.1-8-5.5-8-10.5v-6z"/>',
  circle: '<circle cx="12" cy="12" r="8.5"/>',
  crown: '<path d="M3 18h18l-1.5-9-4.5 3.5L12 5l-3 7.5L4.5 12.5z"/>',
  dagger: '<path d="M11 2h2v11h3l-4 9-4-9h3z"/>',
  laurel: '<path d="M12 3c5 2 7 7 5 13-6-1-9-6-8-11 1-1 2-2 3-2z"/>',
  flame:
    '<path d="M12 2c3 5 6 7 6 12a6 6 0 0 1-12 0c0-2 1-4 2-5-.3 2 .6 3 1.3 3 .9 0 1.2-1 .6-2.2C9 7.5 11 5 12 2z"/>',
  mountain: '<path d="M2 19L9 6l4 7 2-3 7 9z"/>',
  moon: '<path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"/>',
  feather: '<path d="M19 3C9 5 4 12 4 21c9-1 15-8 15-18z"/>',
  key: '<path d="M9 2a5 5 0 1 0 0 10 5 5 0 0 0 4.9-6H21v4h-2v3h-3v-3h-1.1A5 5 0 0 0 9 2zM9 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4z"/>',
  book: '<path d="M4 4h7v16H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM13 4h7a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-7z"/>',
  anchor:
    '<circle cx="12" cy="5" r="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v13M6 12H2a10 10 0 0 0 8 9M18 12h4a10 10 0 0 1-8 9M6 15h12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  banner: '<path d="M6 2h13l-3 5 3 5H6v10H4V2z"/>',
  helm: '<path d="M12 2C7.6 2 4 5.4 4 9.6v2.5c0 1.3.5 2.5 1.3 3.4L6.4 21h2.1l.6-2.6h5.8l.6 2.6h2.1l1.1-5.5c.8-.9 1.3-2.1 1.3-3.4V9.6C20 5.4 16.4 2 12 2z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 11h8M9 14h6" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round"/>',
  swordscross:
    '<path d="M4 4l16 16M20 4L4 20" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round"/><path d="M8.5 8.5l2 2M15.5 8.5l-2 2M8.5 15.5l2-2M15.5 15.5l-2-2" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round"/>',
};

export const CARD_SYMBOL_ORDER = [
  "star",
  "diamond",
  "hex",
  "compass",
  "shield",
  "circle",
  "crown",
  "dagger",
  "laurel",
  "flame",
  "mountain",
  "moon",
  "feather",
  "key",
  "book",
  "anchor",
  "banner",
  "helm",
  "swordscross",
];
