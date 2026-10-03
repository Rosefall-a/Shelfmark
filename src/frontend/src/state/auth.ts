import { ref } from "vue";
import { fetchCurrentUser } from "../services/auth";
import type { CurrentUser } from "../services/auth";

export const currentUser = ref<CurrentUser | null>(null);
export const authChecked = ref(false);

export async function checkAuth() {
  try {
    currentUser.value = await fetchCurrentUser();
  } catch {
    // a transient network/server failure here shouldn't leave the app
    // stuck retrying forever on every navigation (router.beforeEach
    // awaits this with no try/catch of its own), treat it the same as
    // "not logged in" and let the next real navigation attempt re-check
    currentUser.value = null;
  }
  authChecked.value = true;
}

export function handleUnauthorized() {
  currentUser.value = null;
  authChecked.value = true;
}
