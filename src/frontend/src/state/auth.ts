import { ref } from "vue";
import { fetchCurrentUser } from "../services/auth";
import type { CurrentUser } from "../services/auth";

export const currentUser = ref<CurrentUser | null>(null);
export const authChecked = ref(false);
export const authCheckFailed = ref(false);

export async function checkAuth() {
  authCheckFailed.value = false;
  try {
    currentUser.value = await fetchCurrentUser();
  } catch {
    authCheckFailed.value = true;
    // Keep auth failure separate from a confirmed unauthenticated response
    // so startup routing can distinguish an unavailable backend from login.
    currentUser.value = null;
  }
  authChecked.value = true;
}
