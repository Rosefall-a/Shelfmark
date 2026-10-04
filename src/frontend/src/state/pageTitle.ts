// The browser tab title: "(2) Hades | Archive". It used to be the Vite
// project name, "frontend", on every page (#85). Pages get a title from their
// route's meta.title; a detail page can override it with the thing it shows.

import { onBeforeUnmount, ref, watch } from "vue";

export const APP_NAME = "Archive";

interface Override {
  owner: symbol;
  title: string;
}

// who set it, so a page that is leaving can't clear the title the next page
// already set
const override = ref<Override | null>(null);

export function pageTitleOverride(): string | null {
  return override.value?.title ?? null;
}

export function formatDocumentTitle(
  title: string | null | undefined,
  unread = 0,
): string {
  const count = unread > 0 ? `(${unread > 99 ? "99+" : unread}) ` : "";
  return `${count}${title ? `${title} | ` : ""}${APP_NAME}`;
}

// Call from a page's setup to title the tab after what it shows, e.g. the
// game's name. Cleared again when the page goes away.
export function usePageTitle(source: () => string | null | undefined): void {
  const owner = Symbol("page-title");
  watch(
    source,
    (title) => {
      if (title) override.value = { owner, title };
      else if (override.value?.owner === owner) override.value = null;
    },
    { immediate: true },
  );
  onBeforeUnmount(() => {
    if (override.value?.owner === owner) override.value = null;
  });
}
