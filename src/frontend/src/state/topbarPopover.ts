import { ref } from "vue";

// The bell and the profile menu both stop click propagation on their
// triggers, so neither one's click-outside handler sees a click on the
// other. Tracking the one open panel here lets each close itself when
// the other opens.
export const openTopbarPopover = ref<"bell" | "profile" | null>(null);
