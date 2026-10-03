<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  getCard,
  updateCard,
  generatePrestigeChallenge,
} from "../services/cards";
import { fetchGame } from "../services/games";
import { fetchSets } from "../services/set";
import { fetchBounty } from "../services/bounties";
import type { Bounty } from "../services/bounties";
import type { Card } from "../types/card";
import type {
  CardCustomization,
  CardFrontTemplate,
  CardBackTemplate,
  CardAccent,
  CardBorderColor,
  CardFace,
  PrestigeVariant,
} from "../types/card";
import {
  DEFAULT_CARD_CUSTOMIZATION,
  CARD_SYMBOLS,
  CARD_SYMBOL_ORDER,
} from "../types/card";
import type { CardRarity } from "../types/card";
import type { Game } from "../types/game";
import type { CardSet } from "../types/set";

const route = useRoute();
const router = useRouter();
const cardId = route.params.cardId as string;

const card = ref<Card | null>(null);
const game = ref<Game | null>(null);
const sets = ref<CardSet[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const saving = ref(false);
const saved = ref(false);
const flipped = ref(false);
const artFailed = ref(false);

const customization = ref<CardCustomization>({ ...DEFAULT_CARD_CUSTOMIZATION });
const rarity = ref<CardRarity | null>(null);
const setId = ref<string | null>(null);
const activeTab = ref<"template" | "prestige" | "symbol" | "data" | "set">(
  "template",
);
const symbolModalOpen = ref(false);

// Prestige is never a manual field — it's a real Bounty the system
// auto-generates once the game's achievements hit 100%, linked via
// card.bountyId. Whether the card is actually prestiged is always
// derived from this bounty's status, never stored on the card itself.
const bounty = ref<Bounty | null>(null);
const generatingPrestige = ref(false);
const prestigeError = ref<string | null>(null);

onMounted(async () => {
  try {
    const c = await getCard(cardId);
    card.value = c;
    customization.value = {
      ...DEFAULT_CARD_CUSTOMIZATION,
      ...(c.cardCustomization ?? {}),
    };
    rarity.value = c.rarity;
    setId.value = c.setId;

    const [g, s] = await Promise.all([fetchGame(c.gameId), fetchSets()]);
    game.value = g;
    sets.value = s;
    if (c.bountyId) {
      bounty.value = await fetchBounty(c.bountyId);
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load card.";
  } finally {
    loading.value = false;
  }
});

const isPrestige = computed(() => bounty.value?.status === "completed");
const achievements100 = computed(() => {
  const g = game.value;
  return !!g && g.achievementTotal > 0 && g.achievementPercent >= 100;
});

async function generatePrestige() {
  if (!card.value) return;
  generatingPrestige.value = true;
  prestigeError.value = null;
  try {
    card.value = await generatePrestigeChallenge(card.value.id);
    if (card.value.bountyId) {
      bounty.value = await fetchBounty(card.value.bountyId);
    }
  } catch (e) {
    prestigeError.value =
      e instanceof Error
        ? e.message
        : "Failed to generate a prestige challenge.";
  } finally {
    generatingPrestige.value = false;
  }
}

const RARITY_LABEL: Record<CardRarity, string> = {
  common: "Common",
  uncommon: "Uncommon",
  rare: "Rare",
  legendary: "Legendary",
  mythic: "Mythic",
};
const ACCENTS: Record<CardAccent, { gold: string; dim: string; soft: string }> =
  {
    gold: { gold: "#c8a35f", dim: "#8f7648", soft: "rgba(200,163,95,0.32)" },
    silver: { gold: "#c9ccd6", dim: "#8c8f99", soft: "rgba(201,204,214,0.32)" },
    bronze: { gold: "#b8793f", dim: "#8a5c33", soft: "rgba(184,121,63,0.32)" },
    copper: { gold: "#c17a52", dim: "#8f5b3d", soft: "rgba(193,122,82,0.32)" },
    rose: { gold: "#c99383", dim: "#93695d", soft: "rgba(201,147,131,0.32)" },
  };

const accentVars = computed(() => {
  const a = ACCENTS[customization.value.accent];
  return { "--gold": a.gold, "--gold-dim": a.dim, "--gold-soft": a.soft };
});

// ---- symbol rendering: built-in SVG paths, tinted-upload image, or none ----
function symbolInner(which?: string): string {
  const key = which || customization.value.symbol;
  return CARD_SYMBOLS[key] || "";
}
const rotStyle = computed(
  () => `rotate(${customization.value.symbolRotation}deg)`,
);
const hasSecondarySymbol = computed(
  () =>
    customization.value.symbol2 !== "none" && !customization.value.customSymbol,
);

function onCustomSymbolUpload(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    customization.value.customSymbol = ev.target?.result as string;
  };
  reader.readAsDataURL(file);
}
function clearCustomSymbol() {
  customization.value.customSymbol = null;
}

// ---- card art: the game's real cover art by default, swappable per card ----
const artSrc = computed(
  () => customization.value.customArt || game.value?.coverImageUrl || null,
);
function onArtUpload(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  artFailed.value = false;
  const reader = new FileReader();
  reader.onload = (ev) => {
    customization.value.customArt = ev.target?.result as string;
  };
  reader.readAsDataURL(file);
}
function resetArt() {
  customization.value.customArt = null;
  artFailed.value = false;
}

// ---- hover tilt: the card leans toward whichever corner the cursor is
// nearest, a small independent 3D layer nested inside the click-to-flip
// layer so the two transforms compose instead of fighting each other ----
const tiltX = ref(0);
const tiltY = ref(0);
const MAX_TILT = 12;
function onCardMouseMove(e: MouseEvent) {
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const px = (e.clientX - rect.left) / rect.width - 0.5;
  const py = (e.clientY - rect.top) / rect.height - 0.5;
  tiltY.value = px * MAX_TILT * 2;
  tiltX.value = -py * MAX_TILT * 2;
}
function onCardMouseLeave() {
  tiltX.value = 0;
  tiltY.value = 0;
}

const rarityLetter = computed(() =>
  rarity.value ? rarity.value.charAt(0).toUpperCase() : "?",
);

// ---- derived card content, straight from the real game record ----
const platformLabel = computed(
  () => game.value?.platforms[0]?.platform ?? game.value?.source ?? "PC",
);
const playtimeLabel = computed(() => {
  const minutes = game.value?.platforms[0]?.playtimeMinutes ?? 0;
  if (!minutes) return null;
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return hrs >= 1000 ? `${hrs.toLocaleString()}h` : `${hrs}h ${mins}m`;
});
const achievementLabel = computed(() => {
  const g = game.value;
  if (!g || !g.achievementTotal) return null;
  const unlocked =
    g.achievements.filter((a) => a.unlockedAt).length ||
    Math.round((g.achievementPercent / 100) * g.achievementTotal);
  return `${unlocked} / ${g.achievementTotal} achievements unlocked.`;
});
const statusWord = computed(() =>
  game.value?.status === "mastered" ? "Mastered" : "Beaten",
);
const completionYear = computed(() => {
  const d = game.value?.completionDate;
  return d ? new Date(d).getFullYear() : null;
});
const currentSet = computed(
  () => sets.value.find((s) => s.id === setId.value) ?? null,
);
const setPositionLabel = computed(() => {
  if (!currentSet.value || !card.value) return null;
  // position within the set: this card's own rank among the set's cards
  // by archive number, matching the set's already-established ordering
  return currentSet.value.targetTotal
    ? `${String(currentSet.value.cardCount).padStart(2, "0")}/${currentSet.value.targetTotal}`
    : null;
});
const setComplete = computed(() => currentSet.value?.isComplete ?? false);

async function saveCard() {
  if (!card.value) return;
  saving.value = true;
  saved.value = false;
  try {
    card.value = await updateCard(card.value.id, {
      setId: setId.value,
      rarity: rarity.value,
      cardCustomization: customization.value,
    });
    saved.value = true;
    sets.value = await fetchSets();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to save card.";
  } finally {
    saving.value = false;
  }
}

watch(
  [customization, rarity, setId],
  () => {
    saved.value = false;
  },
  { deep: true },
);

function printCard() {
  window.print();
}

const frontTemplates: {
  value: CardFrontTemplate;
  label: string;
  hint: string;
}[] = [
  { value: "classic", label: "Classic", hint: "Full art, thin gold ring" },
  { value: "borderless", label: "Borderless", hint: "Art to the very edge" },
  { value: "ornate", label: "Ornate", hint: "Corner flourishes" },
  { value: "minimal", label: "Minimal", hint: "Title & collector line only" },
  {
    value: "bordered",
    label: "Bordered",
    hint: "Solid frame, art inset inside it",
  },
];
const backTemplates: {
  value: CardBackTemplate;
  label: string;
  hint: string;
}[] = [
  { value: "emblem", label: "Emblem", hint: "Medallion" },
  { value: "collector", label: "Collector", hint: "Compact detail" },
  { value: "record", label: "Record", hint: "Completion record" },
];
const accents: CardAccent[] = ["gold", "silver", "bronze", "copper", "rose"];
const accentSwatch: Record<CardAccent, string> = {
  gold: "#c8a35f",
  silver: "#c9ccd6",
  bronze: "#b8793f",
  copper: "#c17a52",
  rose: "#c99383",
};
const borderColors: { value: CardBorderColor; label: string; hint: string }[] =
  [
    { value: "black", label: "Black", hint: "The standard border color" },
    { value: "white", label: "White", hint: "The alternate print color" },
    { value: "accent", label: "Accent", hint: "Matches the metal accent" },
  ];
const cardFaces: { value: CardFace; label: string; hint: string }[] = [
  { value: "dark", label: "Dark", hint: "The default look" },
  { value: "parchment", label: "Parchment", hint: "Real parchment, dark ink" },
];
const titlePositions: {
  value: "top" | "bottom";
  label: string;
  hint: string;
}[] = [
  { value: "top", label: "Top of card", hint: "The usual spot" },
  {
    value: "bottom",
    label: "Merged into stats",
    hint: "For art with its own logo up top",
  },
];
const prestigeVariants: {
  value: PrestigeVariant;
  label: string;
  hint: string;
}[] = [
  { value: "foil", label: "Foil", hint: "Reflective sheen" },
  { value: "engraved", label: "Engraved", hint: "Etched, restrained" },
  { value: "ceremonial", label: "Ceremonial", hint: "Heavier ornate frame" },
  { value: "minimal", label: "Minimal", hint: "Barely there" },
];
const rarities: CardRarity[] = [
  "common",
  "uncommon",
  "rare",
  "legendary",
  "mythic",
];
</script>

<template>
  <main class="designer-page">
    <div class="designer-header">
      <button type="button" class="back-btn" @click="router.push('/cards')">
        &larr; All cards
      </button>
      <h1 v-if="game && card">
        {{ game.title }}
        <span class="archive-num"
          >#{{ String(card.archiveNumber ?? 0).padStart(3, "0") }}</span
        >
      </h1>
    </div>

    <p v-if="loading" class="empty-state">Loading…</p>
    <p v-else-if="error" class="empty-state error">{{ error }}</p>

    <div v-else-if="game && card" class="designer-layout">
      <div class="stage">
        <div
          class="flip-scene"
          :style="accentVars"
          @mousemove="onCardMouseMove"
          @mouseleave="onCardMouseLeave"
          @click="flipped = !flipped"
        >
          <div class="flip-card" :class="{ flipped }">
            <div
              class="tilt-layer"
              :style="{
                transform: `rotateX(${flipped ? -tiltX : tiltX}deg) rotateY(${tiltY}deg)`,
              }"
            >
              <!-- ============ FRONT ============ -->
              <div
                class="card-face card-front"
                :data-template="customization.frontTemplate"
                :data-border-color="customization.borderColor"
                :data-face="customization.cardFace"
                :data-prestige="isPrestige"
                :data-prestige-variant="customization.prestigeVariant"
                :data-title-pos="customization.titlePosition"
              >
                <div class="card-inner">
                  <div class="art-layer">
                    <img
                      v-if="artSrc && !artFailed"
                      :src="artSrc"
                      alt=""
                      @error="artFailed = true"
                    />
                    <div v-else class="art-fallback"></div>
                  </div>

                  <div class="corner tl"></div>
                  <div class="corner br"></div>

                  <div class="content">
                    <div class="row row-title plate" id="rowTitleBar">
                      <span class="title-name">{{ game.title }}</span>
                      <span class="title-meta"
                        >{{ platformLabel }} &middot; #{{
                          String(card.archiveNumber ?? 0).padStart(3, "0")
                        }}</span
                      >
                    </div>

                    <div class="bottom-stack">
                      <div class="rules-box plate">
                        <div class="row row-type">
                          <span class="type-text">Achievement</span>
                          <span class="type-title">{{ game.title }}</span>
                          <span
                            class="type-sym icon-slot"
                            :style="{ transform: rotStyle }"
                          >
                            <img
                              v-if="customization.customSymbol"
                              :src="customization.customSymbol"
                              alt=""
                            />
                            <svg
                              v-else
                              viewBox="0 0 24 24"
                              fill="currentColor"
                              v-html="symbolInner()"
                            ></svg>
                          </span>
                        </div>
                        <div class="row row-text">
                          <p v-if="achievementLabel" class="stat-line">
                            {{ achievementLabel }}
                          </p>
                          <p v-if="playtimeLabel" class="stat-line">
                            {{ playtimeLabel }} played.
                          </p>
                          <p v-if="game.ratingOverall" class="stat-line">
                            Rated {{ game.ratingOverall.toFixed(1) }} / 10.
                          </p>
                          <div class="stat-rule"></div>
                          <p class="flavor-line">
                            {{ statusWord
                            }}<template v-if="completionYear">
                              &middot; {{ completionYear }}</template
                            >
                          </p>
                        </div>
                      </div>

                      <div class="row row-collector plate">
                        <span class="collector-left">
                          <span
                            class="collector-sym icon-slot"
                            :style="{ transform: rotStyle }"
                          >
                            <img
                              v-if="customization.customSymbol"
                              :src="customization.customSymbol"
                              alt=""
                            />
                            <svg
                              v-else
                              viewBox="0 0 24 24"
                              fill="currentColor"
                              v-html="symbolInner()"
                            ></svg>
                          </span>
                          <template v-if="setPositionLabel">
                            {{ setPositionLabel }}
                            <span v-if="setComplete" class="set-complete-tag"
                              >COMPLETE</span
                            >
                            &middot;
                          </template>
                          {{ rarityLetter }}
                        </span>
                        <span class="collector-right">{{
                          game.developer || ""
                        }}</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="prestige-shine"></div>
                <div class="grain"></div>
              </div>

              <!-- ============ BACK ============ -->
              <div
                class="card-face card-back-inner"
                :data-face="customization.cardFace"
              >
                <div
                  class="back-emblem"
                  v-show="customization.backTemplate === 'emblem'"
                >
                  <div class="back-corner tl"></div>
                  <div class="back-corner br"></div>
                  <div class="medallion">
                    <span class="icon-slot" :style="{ transform: rotStyle }">
                      <img
                        v-if="customization.customSymbol"
                        :src="customization.customSymbol"
                        alt=""
                      />
                      <svg
                        v-else
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        v-html="symbolInner()"
                      ></svg>
                    </span>
                    <div class="medallion-badge" v-if="hasSecondarySymbol">
                      <span class="icon-slot">
                        <svg
                          viewBox="0 0 24 24"
                          fill="currentColor"
                          v-html="symbolInner(customization.symbol2)"
                        ></svg>
                      </span>
                    </div>
                  </div>
                  <div class="back-wordmark">ARCHIVE</div>
                  <div class="back-setname">
                    {{ currentSet?.name || "No set" }}
                  </div>
                  <div class="back-num">
                    #{{ String(card.archiveNumber ?? 0).padStart(3, "0") }}
                  </div>
                </div>

                <div
                  class="back-collector"
                  v-show="customization.backTemplate === 'collector'"
                >
                  <div class="back-corner tl"></div>
                  <div class="back-corner br"></div>
                  <div class="medallion">
                    <span class="icon-slot" :style="{ transform: rotStyle }">
                      <img
                        v-if="customization.customSymbol"
                        :src="customization.customSymbol"
                        alt=""
                      />
                      <svg
                        v-else
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        v-html="symbolInner()"
                      ></svg>
                    </span>
                  </div>
                  <div class="bc-panel">
                    <div class="bc-title">{{ game.title }}</div>
                    <div class="bc-stat-grid">
                      <div class="bc-stat">
                        <span class="lbl">Set</span
                        ><span class="val">{{ setPositionLabel || "–" }}</span>
                      </div>
                      <div class="bc-stat">
                        <span class="lbl">Platform</span
                        ><span class="val">{{ platformLabel }}</span>
                      </div>
                      <div class="bc-stat">
                        <span class="lbl">Completed</span
                        ><span class="val">{{ completionYear || "–" }}</span>
                      </div>
                      <div class="bc-stat">
                        <span class="lbl">Playtime</span
                        ><span class="val">{{ playtimeLabel || "–" }}</span>
                      </div>
                    </div>
                    <div class="bc-pills">
                      <span class="bc-pill">{{
                        rarity ? RARITY_LABEL[rarity] : "Unrated"
                      }}</span>
                      <span class="bc-pill bc-pill-prestige" v-if="isPrestige"
                        >Prestiged</span
                      >
                    </div>
                    <div
                      class="bc-section"
                      v-if="customization.memorableAchievement"
                    >
                      <span class="lbl">Memorable achievement</span>
                      <div class="val">
                        {{ customization.memorableAchievement }}
                      </div>
                    </div>
                    <div class="bc-section" v-if="customization.personalNote">
                      <span class="lbl">Personal note</span>
                      <div class="val bc-note">
                        {{ customization.personalNote }}
                      </div>
                    </div>
                    <div class="bc-section" v-if="isPrestige && bounty">
                      <span class="lbl">The challenge</span>
                      <div class="val bc-note">{{ bounty.title }}</div>
                    </div>
                  </div>
                </div>

                <div
                  class="back-record"
                  v-show="customization.backTemplate === 'record'"
                >
                  <div class="back-corner tl"></div>
                  <div class="back-corner br"></div>
                  <div class="record-top">
                    <span class="icon-slot">
                      <img
                        v-if="customization.customSymbol"
                        :src="customization.customSymbol"
                        alt=""
                      />
                      <svg
                        v-else
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        v-html="symbolInner()"
                      ></svg>
                    </span>
                    <span class="record-top-label">Archive Card</span>
                    <span class="record-top-num"
                      >#{{
                        String(card.archiveNumber ?? 0).padStart(3, "0")
                      }}</span
                    >
                  </div>
                  <div class="record-main">
                    <div class="record-title">{{ game.title }}</div>
                    <div class="record-completed">
                      {{ statusWord
                      }}<template v-if="completionYear">
                        {{ completionYear }}</template
                      >
                    </div>
                    <div class="record-stats">
                      {{ platformLabel
                      }}<template v-if="playtimeLabel">
                        &middot; {{ playtimeLabel }}</template
                      >
                    </div>
                  </div>
                  <div
                    class="record-moment"
                    v-if="customization.memorableAchievement"
                  >
                    <div class="record-moment-label">
                      Most memorable achievement
                    </div>
                    <div class="record-moment-name">
                      {{ customization.memorableAchievement }}
                    </div>
                    <div
                      class="record-moment-desc"
                      v-if="customization.personalNote"
                    >
                      {{ customization.personalNote }}
                    </div>
                  </div>
                  <div class="record-bottom">
                    <span>{{ currentSet ? currentSet.name : "No set" }}</span>
                    <span>{{ rarity ? RARITY_LABEL[rarity] : "Unrated" }}</span>
                  </div>
                </div>
                <div class="grain"></div>
              </div>
            </div>
          </div>
        </div>
        <div class="stage-actions">
          <button
            type="button"
            class="flip-btn"
            @click.stop="flipped = !flipped"
          >
            Flip card
          </button>
          <button type="button" class="flip-btn" @click.stop="printCard">
            Print
          </button>
        </div>
        <p class="print-note">
          Prints both faces at true 2.5&times;3.5in size. Foil is simulated, not
          real foil.
        </p>
      </div>

      <aside class="panel">
        <div class="tabs">
          <button
            type="button"
            class="tab"
            :class="{ active: activeTab === 'template' }"
            @click="activeTab = 'template'"
          >
            Template
          </button>
          <button
            type="button"
            class="tab"
            :class="{ active: activeTab === 'prestige' }"
            @click="activeTab = 'prestige'"
          >
            Prestige
          </button>
          <button
            type="button"
            class="tab"
            :class="{ active: activeTab === 'symbol' }"
            @click="activeTab = 'symbol'"
          >
            Symbol
          </button>
          <button
            type="button"
            class="tab"
            :class="{ active: activeTab === 'data' }"
            @click="activeTab = 'data'"
          >
            Data
          </button>
          <button
            type="button"
            class="tab"
            :class="{ active: activeTab === 'set' }"
            @click="activeTab = 'set'"
          >
            Rarity &amp; Set
          </button>
        </div>

        <div class="tab-panels">
          <div class="tab-panel" v-show="activeTab === 'template'">
            <div class="field">
              <label>Front template</label>
              <div class="tpl-grid">
                <button
                  v-for="t in frontTemplates"
                  :key="t.value"
                  type="button"
                  class="tpl-btn"
                  :class="{ active: customization.frontTemplate === t.value }"
                  @click="customization.frontTemplate = t.value"
                >
                  {{ t.label }}<span>{{ t.hint }}</span>
                </button>
              </div>
            </div>
            <div
              class="field"
              v-if="customization.frontTemplate === 'bordered'"
            >
              <label>Border color</label>
              <div class="tpl-grid">
                <button
                  v-for="b in borderColors"
                  :key="b.value"
                  type="button"
                  class="tpl-btn"
                  :class="{ active: customization.borderColor === b.value }"
                  @click="customization.borderColor = b.value"
                >
                  {{ b.label }}<span>{{ b.hint }}</span>
                </button>
              </div>
            </div>
            <div class="field">
              <label>Title position</label>
              <div class="tpl-grid">
                <button
                  v-for="t in titlePositions"
                  :key="t.value"
                  type="button"
                  class="tpl-btn"
                  :class="{ active: customization.titlePosition === t.value }"
                  @click="customization.titlePosition = t.value"
                >
                  {{ t.label }}<span>{{ t.hint }}</span>
                </button>
              </div>
            </div>
            <div class="field">
              <label>Back template</label>
              <div class="tpl-grid">
                <button
                  v-for="t in backTemplates"
                  :key="t.value"
                  type="button"
                  class="tpl-btn"
                  :class="{ active: customization.backTemplate === t.value }"
                  @click="customization.backTemplate = t.value"
                >
                  {{ t.label }}<span>{{ t.hint }}</span>
                </button>
              </div>
            </div>
            <div class="field">
              <label>Card face</label>
              <div class="tpl-grid">
                <button
                  v-for="f in cardFaces"
                  :key="f.value"
                  type="button"
                  class="tpl-btn"
                  :class="{ active: customization.cardFace === f.value }"
                  @click="customization.cardFace = f.value"
                >
                  {{ f.label }}<span>{{ f.hint }}</span>
                </button>
              </div>
            </div>
            <div class="field">
              <label>Metal accent</label>
              <div class="accent-grid">
                <button
                  v-for="a in accents"
                  :key="a"
                  type="button"
                  class="accent-btn"
                  :class="{ active: customization.accent === a }"
                  :style="{ background: accentSwatch[a] }"
                  @click="customization.accent = a"
                ></button>
              </div>
            </div>
          </div>

          <div class="tab-panel" v-show="activeTab === 'prestige'">
            <template v-if="!achievements100">
              <div class="field">
                <label>Prestige</label>
                <div class="field-hint">
                  Earn every achievement in {{ game?.title }} to unlock a
                  prestige challenge. There's nothing to pick here. The system
                  generates the challenge itself once you're at 100%.
                </div>
              </div>
            </template>
            <template v-else-if="!bounty">
              <div class="field">
                <label>Prestige</label>
                <div class="field-hint">
                  100% complete. Generate the one prestige challenge for this
                  card, a real goal built from {{ game?.title }}'s own data,
                  tracked and verified through Bounties.
                </div>
                <button
                  type="button"
                  class="primary-btn"
                  :disabled="generatingPrestige"
                  @click="generatePrestige"
                >
                  {{
                    generatingPrestige
                      ? "Generating…"
                      : "Generate prestige challenge"
                  }}
                </button>
                <div class="field-hint error" v-if="prestigeError">
                  {{ prestigeError }}
                </div>
              </div>
            </template>
            <template v-else>
              <div class="field">
                <label>Prestige challenge</label>
                <div class="prestige-status">
                  <div class="prestige-status-title">{{ bounty.title }}</div>
                  <span
                    class="bc-pill"
                    :class="{
                      'bc-pill-prestige': bounty.status === 'completed',
                    }"
                    >{{ bounty.status.replace("_", " ") }}</span
                  >
                </div>
                <div class="field-hint">{{ bounty.description }}</div>
                <router-link class="reset-link" to="/bounties"
                  >Manage in Bounties &rarr;</router-link
                >
              </div>
              <div class="field" v-if="isPrestige">
                <label>Prestige treatment</label>
                <div class="tpl-grid">
                  <button
                    v-for="v in prestigeVariants"
                    :key="v.value"
                    type="button"
                    class="tpl-btn"
                    :class="{
                      active: customization.prestigeVariant === v.value,
                    }"
                    @click="customization.prestigeVariant = v.value"
                  >
                    {{ v.label }}<span>{{ v.hint }}</span>
                  </button>
                </div>
              </div>
            </template>
          </div>

          <div class="tab-panel" v-show="activeTab === 'symbol'">
            <div class="field">
              <label>Primary symbol</label>
              <button
                type="button"
                class="symbol-trigger"
                @click="symbolModalOpen = true"
              >
                <span class="icon-slot" :style="{ transform: rotStyle }">
                  <img
                    v-if="customization.customSymbol"
                    :src="customization.customSymbol"
                    alt=""
                  />
                  <svg
                    v-else
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    v-html="symbolInner()"
                  ></svg>
                </span>
                <span class="symbol-trigger-text">Choose symbol&hellip;</span>
              </button>
            </div>
          </div>

          <div class="tab-panel" v-show="activeTab === 'data'">
            <div class="field">
              <label>Card art</label>
              <label class="upload-btn">
                <span>{{
                  customization.customArt
                    ? "Replace card art"
                    : "Upload card art"
                }}</span>
                <input type="file" accept="image/*" @change="onArtUpload" />
              </label>
              <div class="field-hint">
                Uses the game's own cover art by default. Nothing leaves your
                browser.
              </div>
              <button
                v-if="customization.customArt"
                type="button"
                class="reset-link"
                @click="resetArt"
              >
                Reset to game cover
              </button>
            </div>
            <div class="field">
              <label>Memorable achievement</label>
              <input
                v-model="customization.memorableAchievement"
                type="text"
                maxlength="80"
                class="text-input"
                placeholder="The one you actually want remembered"
              />
            </div>
            <div class="field">
              <label>Personal note (back only)</label>
              <textarea
                v-model="customization.personalNote"
                maxlength="300"
                class="text-input textarea-input"
                placeholder="Why it mattered"
              ></textarea>
            </div>
          </div>

          <div class="tab-panel" v-show="activeTab === 'set'">
            <div class="field">
              <label>Rarity</label>
              <div class="rarity-grid">
                <button
                  v-for="r in rarities"
                  :key="r"
                  type="button"
                  class="rarity-btn"
                  :class="{ active: rarity === r }"
                  @click="rarity = r"
                >
                  {{ RARITY_LABEL[r] }}
                </button>
              </div>
            </div>
            <div class="field">
              <label>Set</label>
              <select v-model="setId" class="select-input">
                <option :value="null">No set</option>
                <option v-for="s in sets" :key="s.id" :value="s.id">
                  {{ s.name }}
                </option>
              </select>
              <div class="field-hint">Manage sets from the Sets page.</div>
            </div>
          </div>
        </div>

        <div class="panel-actions">
          <button
            type="button"
            class="save-btn"
            :disabled="saving"
            @click="saveCard"
          >
            {{ saving ? "Saving…" : saved ? "Saved" : "Save" }}
          </button>
        </div>
      </aside>
    </div>

    <!-- ============ SYMBOL MODAL ============ -->
    <div
      class="modal-backdrop"
      v-if="symbolModalOpen"
      @click.self="symbolModalOpen = false"
    >
      <div class="modal" role="dialog" aria-label="Symbol">
        <div class="modal-head">
          <h2>Symbol</h2>
          <button
            type="button"
            class="modal-close"
            @click="symbolModalOpen = false"
          >
            &times;
          </button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label>Primary symbol</label>
            <div class="icon-picker-grid">
              <button
                v-for="key in CARD_SYMBOL_ORDER"
                :key="key"
                type="button"
                class="icon-btn"
                :class="{ active: customization.symbol === key }"
                @click="customization.symbol = key"
              >
                <span class="icon-slot"
                  ><svg
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    v-html="symbolInner(key)"
                  ></svg
                ></span>
              </button>
            </div>
          </div>
          <div class="field">
            <label>Rotation</label>
            <div class="slider-field">
              <div class="sf-head">
                <span>Tilts the primary symbol wherever it's shown</span
                ><b>{{ customization.symbolRotation }}&deg;</b>
              </div>
              <input
                v-model.number="customization.symbolRotation"
                type="range"
                min="-45"
                max="45"
              />
            </div>
          </div>
          <div class="field">
            <label
              >Combine with a second symbol (back medallion badge only)</label
            >
            <div class="icon-picker-grid">
              <button
                type="button"
                class="icon-btn none-btn"
                :class="{ active: customization.symbol2 === 'none' }"
                @click="customization.symbol2 = 'none'"
              >
                None
              </button>
              <button
                v-for="key in CARD_SYMBOL_ORDER"
                :key="key"
                type="button"
                class="icon-btn"
                :class="{ active: customization.symbol2 === key }"
                @click="customization.symbol2 = key"
              >
                <span class="icon-slot"
                  ><svg
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    v-html="symbolInner(key)"
                  ></svg
                ></span>
              </button>
            </div>
          </div>
          <div class="field">
            <label>Or upload your own icon</label>
            <div class="custom-icon-row">
              <span class="icon-slot" v-if="customization.customSymbol"
                ><img :src="customization.customSymbol" alt=""
              /></span>
              <label class="small-upload-btn">
                <span>Upload icon</span>
                <input
                  type="file"
                  accept="image/*"
                  @change="onCustomSymbolUpload"
                />
              </label>
              <button
                v-if="customization.customSymbol"
                class="reset-link"
                type="button"
                @click="clearCustomSymbol"
              >
                Remove
              </button>
            </div>
            <div class="field-hint">
              Tinted to match the metal accent, replaces the built-in symbol
              everywhere.
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button
            type="button"
            class="primary-btn"
            @click="symbolModalOpen = false"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.designer-page {
  --ink: #141110;
  --panel: #1b1713;
  --panel-2: #231e18;
  --line: #3c3527;
  --parchment: #efe6d3;
  --text: #e9dfc9;
  --text-dim: #a99a7c;
  --text-faint: #7d715a;
  --frame: #100d09;
  --frame-2: #171209;
  /* the panel/tabs/buttons always use this static gold, matching the
     prototype exactly — only the card faces themselves follow the chosen
     metal accent (applied inline on .flip-card, overriding these) */
  --gold: #c8a35f;
  --gold-dim: #8f7648;
  --gold-soft: rgba(200, 163, 95, 0.32);
  min-height: 100vh;
  background: var(--ink);
  color: var(--text);
  padding: 24px;
  box-sizing: border-box;
  font-family: "EB Garamond", Georgia, serif;
}
.designer-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}
.back-btn {
  align-self: flex-start;
  background: none;
  border: none;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0;
  font-family: inherit;
}
.back-btn:hover {
  color: #c8a35f;
}
.designer-header h1 {
  margin: 0;
  font-family: "Cinzel", Georgia, serif;
  font-size: 1.3rem;
  color: var(--parchment);
}
.archive-num {
  color: var(--text-faint);
  font-size: 0.9rem;
  font-weight: 400;
  font-family: "JetBrains Mono", monospace;
}
.empty-state {
  color: var(--text-faint);
}
.empty-state.error {
  color: #e08a7d;
}

.designer-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 32px;
  align-items: start;
}
@media (max-width: 1000px) {
  .designer-layout {
    grid-template-columns: 1fr;
  }
}

.stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  position: sticky;
  top: 24px;
}
.flip-scene {
  width: min(370px, 78vw);
  aspect-ratio: 5 / 7;
  perspective: 1800px;
  cursor: pointer;
}
.flip-card {
  position: relative;
  width: 100%;
  height: 100%;
  transform-style: preserve-3d;
  transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1);
}
.flip-card.flipped {
  transform: rotateY(180deg);
}
/* a second, independent 3D layer nested inside the flip — this is what
   actually leans toward the cursor. Kept separate from .flip-card so the
   click-flip's 0.6s ease and the hover-tilt's snappier 0.15s ease never
   fight over the same transition */
.tilt-layer {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
  transition: transform 0.15s ease-out;
}
@media (prefers-reduced-motion: reduce) {
  .flip-card,
  .tilt-layer {
    transition: none;
  }
}

.card-face {
  position: absolute;
  inset: 0;
  border-radius: 4.4% / 3.2%;
  overflow: hidden;
  backface-visibility: hidden;
  background: var(--frame);
  box-shadow:
    0 26px 64px -20px rgba(0, 0, 0, 0.78),
    0 6px 18px rgba(0, 0, 0, 0.45);
}
.card-back-inner {
  transform: rotateY(180deg);
}

.card-front {
  outline: 1.5px solid var(--gold-dim);
  outline-offset: -1.5px;
}
.card-inner {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}
.art-layer {
  position: absolute;
  inset: 0;
  overflow: hidden;
  background: var(--panel);
}
.art-layer img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  user-select: none;
  pointer-events: none;
}
.art-fallback {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(
      85% 65% at 25% 8%,
      rgba(200, 163, 95, 0.22),
      transparent 60%
    ),
    linear-gradient(155deg, #362c1f, #1a1611 45%, #221c2a 75%, #131a22);
}
.content {
  position: absolute;
  inset: 0;
  z-index: 2;
  padding: 4% 4.5%;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
}
.bottom-stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: auto;
}
.row {
  position: relative;
  display: flex;
}
.plate {
  border: 1px solid var(--gold-dim);
  border-radius: 8px;
  background: linear-gradient(
    160deg,
    rgba(22, 18, 13, 0.92),
    rgba(10, 8, 6, 0.92)
  );
  box-shadow:
    0 3px 10px rgba(0, 0, 0, 0.45),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.row-title {
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 2.6% 5%;
}
.title-name {
  font-family: "Cinzel", Georgia, serif;
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 0.02em;
  color: var(--parchment);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.title-meta {
  font-family: "JetBrains Mono", monospace;
  font-size: 8.5px;
  letter-spacing: 0.06em;
  color: var(--text-dim);
  text-transform: uppercase;
  white-space: nowrap;
}
.rules-box {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.row-type {
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 2.6% 5%;
  border-bottom: 1px solid var(--gold-dim);
  background: rgba(0, 0, 0, 0.16);
}
.type-text {
  font-style: italic;
  font-size: 12px;
  color: var(--gold);
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.type-title {
  display: none;
  font-family: "Cinzel", Georgia, serif;
  font-weight: 600;
  font-size: 13px;
  color: var(--parchment);
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-front[data-title-pos="bottom"] #rowTitleBar {
  display: none;
}
.card-front[data-title-pos="bottom"] .type-text {
  display: none;
}
.card-front[data-title-pos="bottom"] .type-title {
  display: block;
}
.card-front[data-template="minimal"][data-title-pos="bottom"] #rowTitleBar {
  display: flex;
}
.type-sym {
  width: 13px;
  height: 13px;
  color: var(--gold);
  flex-shrink: 0;
}
.row-text {
  flex-direction: column;
  justify-content: flex-start;
  gap: 0;
  padding: 3% 5% 3.5%;
}
.stat-line {
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.5;
  margin: 0;
}
.stat-rule {
  height: 1px;
  background: linear-gradient(to right, var(--gold-soft), transparent 80%);
  margin: 5px 0 6px;
}
.flavor-line {
  font-style: italic;
  font-size: 11.5px;
  color: var(--gold);
  line-height: 1.5;
  margin: 0;
}
.row-collector {
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 1.8% 5%;
  font-family: "JetBrains Mono", monospace;
  font-size: 8px;
  letter-spacing: 0.04em;
  color: var(--text-dim);
}
.collector-left {
  display: flex;
  align-items: center;
  gap: 4px;
  text-transform: uppercase;
}
.collector-right {
  display: flex;
  align-items: center;
  gap: 4px;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
}

.icon-slot {
  display: inline-flex;
  flex-shrink: 0;
}
.icon-slot svg {
  width: 100%;
  height: 100%;
}
.icon-slot img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  filter: sepia(1) saturate(3) hue-rotate(-10deg) brightness(0.95)
    contrast(1.05);
}
.type-sym.icon-slot {
  width: 13px;
  height: 13px;
  color: var(--gold);
}
.collector-sym.icon-slot {
  width: 9px;
  height: 9px;
  color: var(--gold-dim);
}

.prestige-shine {
  position: absolute;
  inset: 0;
  z-index: 5;
  pointer-events: none;
  mix-blend-mode: color-dodge;
  opacity: 0;
  background-size: 220% 220%;
}
.card-front[data-prestige="true"][data-prestige-variant="foil"]
  .prestige-shine {
  opacity: 0.4;
  animation: shine 5.5s ease-in-out infinite;
  background: linear-gradient(
    115deg,
    transparent 30%,
    rgba(255, 255, 255, 0.5) 46%,
    rgba(230, 200, 140, 0.3) 52%,
    transparent 68%
  );
}
@media (prefers-reduced-motion: reduce) {
  .prestige-shine {
    animation: none !important;
    background-position: 30% 30%;
  }
}
@keyframes shine {
  0% {
    background-position: 0% 0%;
  }
  50% {
    background-position: 100% 100%;
  }
  100% {
    background-position: 0% 0%;
  }
}
.card-front[data-prestige="true"] {
  outline-color: var(--gold);
  box-shadow: inset 0 0 0 1px var(--gold);
}
.card-front[data-prestige="true"][data-prestige-variant="engraved"] .title-name,
.card-front[data-prestige="true"][data-prestige-variant="engraved"]
  .type-title {
  text-shadow:
    0 1px 0 rgba(255, 255, 255, 0.15),
    0 -1px 0 rgba(0, 0, 0, 0.6);
}
.card-front[data-prestige="true"][data-prestige-variant="ceremonial"] {
  outline-width: 3px;
}
.card-front[data-prestige="true"][data-prestige-variant="minimal"] {
  outline-width: 2px;
  box-shadow: none;
}

.card-front[data-template="borderless"] {
  outline: none;
}
.card-front[data-template="borderless"] .plate {
  border-color: rgba(200, 163, 95, 0.4);
  background: linear-gradient(
    160deg,
    rgba(14, 11, 8, 0.72),
    rgba(9, 7, 5, 0.78)
  );
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
}
.card-front[data-template="borderless"] .row-type {
  background: rgba(0, 0, 0, 0.1);
  border-bottom-color: rgba(200, 163, 95, 0.4);
}

.corner {
  position: absolute;
  width: 9%;
  aspect-ratio: 1;
  border: 1.5px solid transparent;
  opacity: 0.9;
  z-index: 3;
  pointer-events: none;
}
.corner.tl {
  top: 2%;
  left: 2%;
  border-right: none;
  border-bottom: none;
}
.corner.br {
  bottom: 2%;
  right: 2%;
  border-left: none;
  border-top: none;
}
.card-front[data-template="ornate"] .corner,
.card-front[data-prestige="true"][data-prestige-variant="ceremonial"] .corner {
  border-color: var(--gold);
}
.card-front[data-template="ornate"] {
  outline-width: 2.5px;
  outline-color: var(--gold);
}
.card-front[data-template="ornate"] .plate {
  border-color: var(--gold);
}
.card-front[data-template="minimal"] .rules-box {
  display: none;
}

.card-front[data-template="bordered"] {
  padding: 5%;
  background: var(--frame-2);
}
.card-front[data-template="bordered"][data-border-color="white"] {
  background: #f1ede1;
}
.card-front[data-template="bordered"][data-border-color="accent"] {
  background: var(--gold-dim);
}
.card-front[data-template="bordered"] .content {
  padding: 0;
}
.card-front[data-template="bordered"] .plate {
  border-radius: 2px;
  box-shadow: none;
}
.card-front[data-template="bordered"] .bottom-stack {
  gap: 0;
}
.card-front[data-template="bordered"] .card-inner {
  outline: 1px solid rgba(0, 0, 0, 0.55);
  outline-offset: -1px;
}

.card-front[data-face="parchment"] .row-title,
.card-front[data-face="parchment"] .rules-box {
  background: var(--parchment);
}
.card-front[data-face="parchment"] .title-name {
  color: #241d12;
}
.card-front[data-face="parchment"] .title-meta {
  color: #6b5c44;
}
.card-front[data-face="parchment"] .type-title {
  color: #241d12;
}
.card-front[data-face="parchment"] .row-type {
  background: transparent;
  border-bottom-color: rgba(36, 29, 18, 0.35);
}
.card-front[data-face="parchment"] .type-text {
  color: #241d12;
  font-style: normal;
}
.card-front[data-face="parchment"] .type-sym {
  color: #4a3c26;
}
.card-front[data-face="parchment"] .stat-line {
  color: #241d12;
}
.card-front[data-face="parchment"] .stat-rule {
  background: linear-gradient(to right, rgba(36, 29, 18, 0.4), transparent 85%);
}
.card-front[data-face="parchment"] .flavor-line {
  color: #4a3c26;
}
.card-front[data-face="parchment"] .row-collector {
  background: var(--frame-2);
  color: #b7ac91;
  border-top: none;
  box-shadow: inset 0 1px 0 rgba(0, 0, 0, 0.5);
}
.card-front[data-face="parchment"] .collector-sym.icon-slot {
  color: #8f7648;
}
.card-front[data-face="parchment"]:not([data-template="bordered"]) .row-title,
.card-front[data-face="parchment"]:not([data-template="bordered"]) .rules-box {
  border-color: rgba(36, 29, 18, 0.4);
}

.set-complete-tag {
  font-family: "JetBrains Mono", monospace;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #0c0a08;
  background: var(--gold);
  border-radius: 999px;
  padding: 1.5px 6px;
  vertical-align: middle;
}

/* ---- back ---- */
.card-back-inner {
  outline: 1.5px solid var(--gold-dim);
  outline-offset: -1.5px;
  background: radial-gradient(120% 90% at 50% 10%, #241d14, #100d09 70%);
  padding: 2.3%;
}
.back-corner {
  position: absolute;
  width: 8%;
  aspect-ratio: 1;
  border: 1.5px solid var(--gold);
  opacity: 0.75;
  z-index: 3;
  pointer-events: none;
}
.back-corner.tl {
  top: 5.5%;
  left: 5.5%;
  border-right: none;
  border-bottom: none;
}
.back-corner.br {
  bottom: 5.5%;
  right: 5.5%;
  border-left: none;
  border-top: none;
}
.back-emblem,
.back-collector,
.back-record {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 2.2% / 1.6%;
  overflow: hidden;
  border: 1px solid var(--gold-soft);
}
.back-emblem {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  text-align: center;
}
.medallion {
  width: 30%;
  aspect-ratio: 1;
  border-radius: 50%;
  position: relative;
  z-index: 2;
  background: radial-gradient(circle at 35% 28%, #2c2415, #14100a 72%);
  box-shadow:
    0 0 0 2px var(--gold),
    0 0 0 5px rgba(200, 163, 95, 0.18),
    inset 0 3px 8px rgba(0, 0, 0, 0.6),
    0 10px 24px rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
}
.medallion .icon-slot {
  width: 42%;
  height: 42%;
  color: var(--gold);
}
.medallion-badge {
  position: absolute;
  width: 36%;
  aspect-ratio: 1;
  bottom: -6%;
  right: -6%;
  background: var(--frame);
  border: 1.5px solid var(--gold);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--gold);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.5);
  z-index: 3;
}
.medallion-badge .icon-slot {
  width: 52%;
  height: 52%;
}
.back-wordmark {
  font-family: "Cinzel", Georgia, serif;
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 0.16em;
  color: var(--parchment);
  margin-top: 6px;
}
.back-setname {
  font-style: italic;
  font-size: 12px;
  color: var(--gold);
}
.back-num {
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--text-faint);
  margin-top: 2px;
}

.back-collector {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8% 8% 7%;
  gap: 8px;
}
.back-collector .medallion {
  width: 18%;
}
.bc-panel {
  width: 100%;
}
.bc-title {
  font-family: "Cinzel", Georgia, serif;
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 0.03em;
  color: var(--parchment);
  text-align: center;
  padding-bottom: 9px;
  margin-bottom: 9px;
  border-bottom: 1px solid var(--gold-soft);
}
.bc-stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 9px 16px;
  margin-bottom: 11px;
}
.bc-stat {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.bc-stat .lbl {
  font-family: "JetBrains Mono", monospace;
  font-size: 8.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.bc-stat .val {
  font-size: 13.5px;
  color: var(--parchment);
  font-weight: 600;
}
.bc-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 13px;
}
.bc-pill {
  font-family: "JetBrains Mono", monospace;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--gold);
  border: 1px solid var(--gold-soft);
  border-radius: 999px;
  padding: 3.5px 10px;
}
.bc-pill-prestige {
  background: var(--gold);
  color: #14120f;
  border-color: var(--gold);
}
.bc-section {
  margin-top: 11px;
  width: 100%;
}
.bc-section .lbl {
  font-family: "JetBrains Mono", monospace;
  font-size: 8.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: 5px;
  display: block;
}
.bc-section .val {
  font-size: 12.5px;
  color: var(--parchment);
  line-height: 1.5;
}
.bc-note {
  font-style: italic;
  color: var(--text-dim);
}

.back-record {
  display: flex;
  flex-direction: column;
  padding: 7% 8% 6%;
  gap: 0;
  background: radial-gradient(120% 90% at 50% 0%, #221b12, #100d09 70%);
}
.record-top {
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: "JetBrains Mono", monospace;
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--text-dim);
  text-transform: uppercase;
  padding-bottom: 9px;
  border-bottom: 1px solid var(--gold-soft);
}
.record-top .icon-slot {
  width: 13px;
  height: 13px;
  color: var(--gold);
  flex-shrink: 0;
}
.record-top-label {
  flex: 1;
  text-align: center;
}
.record-main {
  text-align: center;
  padding: 12px 0;
}
.record-title {
  font-family: "Cinzel", Georgia, serif;
  font-weight: 600;
  font-size: 19px;
  color: var(--parchment);
}
.record-completed {
  font-style: italic;
  color: var(--gold);
  font-size: 12px;
  margin-top: 5px;
}
.record-stats {
  font-family: "JetBrains Mono", monospace;
  font-size: 9.5px;
  color: var(--text-dim);
  margin-top: 10px;
  letter-spacing: 0.02em;
}
.record-moment {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 4px;
  min-height: 0;
}
.record-moment-label {
  font-family: "JetBrains Mono", monospace;
  font-size: 8.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--gold);
}
.record-moment-name {
  font-family: "Cinzel", Georgia, serif;
  font-weight: 600;
  font-size: 14px;
  color: var(--parchment);
  margin-top: 4px;
}
.record-moment-desc {
  font-style: italic;
  font-size: 11px;
  color: var(--text-dim);
  max-width: 88%;
  line-height: 1.5;
  margin-top: 2px;
}
.record-bottom {
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-family: "JetBrains Mono", monospace;
  font-size: 7.5px;
  letter-spacing: 0.03em;
  color: var(--text-faint);
  padding-top: 9px;
  border-top: 1px solid var(--gold-soft);
}

.grain {
  position: absolute;
  inset: 0;
  z-index: 9;
  pointer-events: none;
  opacity: 0.03;
  background-image: radial-gradient(circle, #fff 1px, transparent 1px);
  background-size: 3px 3px;
}

.stage-actions {
  display: flex;
  gap: 10px;
}
.flip-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--panel-2);
  border: 1px solid var(--line);
  color: var(--text);
  padding: 8px 14px;
  border-radius: 8px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.flip-btn:hover {
  border-color: var(--gold-soft);
  color: var(--gold);
}
.print-note {
  font-size: 11px;
  color: var(--text-faint);
  line-height: 1.5;
  max-width: 340px;
  text-align: center;
  margin: 0;
}

@media print {
  @page {
    size: 2.5in 3.5in;
    margin: 0;
  }
  body * {
    visibility: hidden !important;
  }
  .flip-scene,
  .flip-scene * {
    visibility: visible !important;
  }
  .flip-scene {
    width: 2.5in !important;
    perspective: none !important;
    position: fixed;
    inset: 0;
  }
  .flip-card,
  .tilt-layer {
    transform: none !important;
    transition: none !important;
  }
  .card-face {
    position: relative !important;
    inset: auto !important;
    width: 2.5in !important;
    height: 3.5in !important;
    transform: none !important;
    backface-visibility: visible !important;
    page-break-after: always;
    box-shadow: none !important;
  }
  .prestige-shine {
    animation: none !important;
  }
  .card-front[data-prestige="true"][data-prestige-variant="foil"]
    .prestige-shine {
    opacity: 0.35 !important;
    background-position: 30% 30% !important;
  }
  * {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }
}

/* ---------- properties panel ---------- */
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
}
.tabs {
  display: flex;
  border-bottom: 1px solid var(--line);
  overflow-x: auto;
}
.tab {
  flex: 1;
  padding: 11px 4px;
  text-align: center;
  background: none;
  border: none;
  color: var(--text-faint);
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap;
  transition:
    color 0.15s,
    border-color 0.15s;
}
.tab:hover {
  color: var(--text);
}
.tab.active {
  color: var(--gold);
  border-bottom-color: var(--gold);
}
.tab-panels {
  padding: 18px;
  max-height: 560px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.panel-actions {
  padding: 14px 18px;
  border-top: 1px solid var(--line);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.field label {
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.field-hint {
  font-size: 11.5px;
  color: var(--text-faint);
  line-height: 1.5;
  margin-top: -2px;
}
.field-hint.error {
  color: #e08a7d;
}
.prestige-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.prestige-status-title {
  font-size: 14px;
  color: var(--text);
  font-weight: 600;
}
.select-input,
.text-input {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--text);
  padding: 8px 10px;
  font-family: inherit;
  font-size: 14px;
  width: 100%;
  min-width: 0;
}
.select-input:focus,
.text-input:focus {
  outline: 2px solid var(--gold);
  outline-offset: 1px;
}

.tpl-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.tpl-btn {
  background: var(--panel-2);
  border: 1.5px solid var(--line);
  border-radius: 8px;
  padding: 10px 8px;
  color: var(--text-dim);
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.15s,
    color 0.15s,
    background-color 0.15s;
}
.tpl-btn span {
  display: block;
  font-size: 11px;
  color: var(--text-faint);
  font-weight: 400;
  margin-top: 2px;
  font-style: italic;
}
.tpl-btn:hover {
  border-color: var(--gold-soft);
  color: var(--text);
}
.tpl-btn.active {
  border-color: var(--gold);
  color: var(--gold);
  background: rgba(200, 163, 95, 0.08);
}

.accent-grid {
  display: flex;
  gap: 8px;
}
.accent-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.3);
  transition:
    border-color 0.15s,
    transform 0.15s;
}
.accent-btn:hover {
  transform: scale(1.08);
}
.accent-btn.active {
  border-color: var(--text);
}

.rarity-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 6px;
}
.rarity-btn {
  background: var(--panel-2);
  border: 1.5px solid var(--line);
  border-radius: 7px;
  padding: 8px 2px;
  color: var(--text-dim);
  font-family: "JetBrains Mono", monospace;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.03em;
  cursor: pointer;
  text-align: center;
  text-transform: uppercase;
  transition:
    border-color 0.15s,
    color 0.15s,
    background-color 0.15s;
}
.rarity-btn:hover {
  border-color: var(--gold-soft);
  color: var(--text);
}
.rarity-btn.active {
  border-color: var(--gold);
  color: var(--gold);
  background: rgba(200, 163, 95, 0.1);
}

.symbol-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 9px 12px;
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
  text-align: left;
}
.symbol-trigger:hover {
  border-color: var(--gold-soft);
}
.symbol-trigger .icon-slot {
  width: 20px;
  height: 20px;
  color: var(--gold);
  flex-shrink: 0;
}
.symbol-trigger-text {
  flex: 1;
}

.upload-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1.5px dashed var(--line);
  border-radius: 9px;
  padding: 14px;
  color: var(--text-dim);
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
}
.upload-btn:hover {
  border-color: var(--gold-soft);
  color: var(--gold);
}
.upload-btn input {
  display: none;
}
.textarea-input {
  resize: vertical;
  min-height: 60px;
  font-family: inherit;
}

.slider-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.slider-field .sf-head {
  display: flex;
  justify-content: space-between;
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
  color: var(--text-faint);
}
.slider-field .sf-head b {
  color: var(--text);
  font-weight: 700;
}
input[type="range"] {
  -webkit-appearance: none;
  width: 100%;
  height: 4px;
  background: var(--line);
  border-radius: 999px;
  outline: none;
}
input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  background: var(--gold);
  cursor: pointer;
  border: 2px solid #14120f;
}

.icon-picker-grid {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.icon-btn {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  border: 1.5px solid var(--line);
  background: var(--panel-2);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-dim);
  padding: 0;
  transition:
    border-color 0.15s,
    color 0.15s,
    background-color 0.15s;
}
.icon-btn .icon-slot {
  width: 15px;
  height: 15px;
}
.icon-btn:hover {
  border-color: var(--gold-soft);
  color: var(--text);
}
.icon-btn.active {
  border-color: var(--gold);
  color: var(--gold);
  background: rgba(200, 163, 95, 0.1);
}
.icon-btn.none-btn {
  font-family: "JetBrains Mono", monospace;
  font-size: 8px;
  color: var(--text-faint);
  text-transform: uppercase;
  width: auto;
  padding: 0 8px;
}

.custom-icon-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.custom-icon-row .icon-slot {
  width: 28px;
  height: 28px;
  border: 1.5px solid var(--line);
  border-radius: 7px;
  padding: 5px;
  box-sizing: border-box;
}
.small-upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 7px 11px;
  color: var(--text-dim);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.small-upload-btn:hover {
  border-color: var(--gold-soft);
  color: var(--gold);
}
.small-upload-btn input {
  display: none;
}
.reset-link {
  background: none;
  border: none;
  color: var(--text-faint);
  font-size: 12px;
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
}
.reset-link:hover {
  color: var(--gold);
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(8, 6, 4, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.modal {
  width: 100%;
  max-width: 420px;
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--gold-dim, #8f7648);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 30px 70px -20px rgba(0, 0, 0, 0.8);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  border-bottom: 1px solid var(--line);
}
.modal-head h2 {
  margin: 0;
  font-family: "Cinzel", Georgia, serif;
  font-weight: 600;
  font-size: 16px;
  color: var(--parchment);
}
.modal-close {
  background: none;
  border: none;
  color: var(--text-faint);
  cursor: pointer;
  padding: 4px;
  font-size: 18px;
  line-height: 1;
}
.modal-close:hover {
  color: var(--gold);
}
.modal-body {
  padding: 18px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.modal-foot {
  padding: 14px 18px;
  border-top: 1px solid var(--line);
  display: flex;
  justify-content: flex-end;
}
.primary-btn {
  background: var(--gold);
  color: #14120f;
  border: none;
  border-radius: 8px;
  padding: 9px 20px;
  font-family: inherit;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.save-btn {
  width: 100%;
  background: var(--gold, #c8a35f);
  color: #14120f;
  border: none;
  border-radius: 8px;
  padding: 10px;
  font-weight: 700;
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
}
.save-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
