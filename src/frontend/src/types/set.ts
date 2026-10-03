import type { Card } from "./card";

export interface CardSet {
  id: string;
  name: string;
  description: string | null;
  targetTotal: number | null;
  cardCount: number;
  isComplete: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface CardSetDetail extends CardSet {
  cards: Card[];
}
