<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { currentUser, checkAuth } from "../../state/auth";
import {
  updateProfile,
  uploadProfilePicture,
  profilePictureUrl,
} from "../../services/auth";

const isMock = computed(() => currentUser.value?.id === "mock");

const cacheBust = ref(Date.now());
const avatarUrl = computed(() =>
  currentUser.value
    ? `${profilePictureUrl(currentUser.value.id)}?t=${cacheBust.value}`
    : "",
);
const avatarFailed = ref(false);

const username = ref("");
const email = ref("");
// filled (and refilled after a save) from the signed-in user rather than
// captured once at setup, so the fields are never blank if this mounts
// before the account has finished loading
watch(
  currentUser,
  (u) => {
    if (!u) return;
    username.value = u.username;
    email.value = u.email;
  },
  { immediate: true },
);
const currentPassword = ref("");
const newPassword = ref("");
const saving = ref(false);
const saveError = ref<string | null>(null);
const saveSuccess = ref(false);

// otherwise "Profile updated." keeps showing after a successful save even
// once the user starts typing something new, reading as if the in-progress
// edit was already saved. Only username/email, not the password fields,
// saveProfile() itself clears those right after a successful save, and
// watching them here would stomp saveSuccess back to false in that same tick.
watch([username, email], () => {
  saveSuccess.value = false;
});

const uploading = ref(false);
const uploadError = ref<string | null>(null);

async function saveProfile() {
  if (newPassword.value && !currentPassword.value) {
    saveError.value = "Enter your current password to set a new one.";
    return;
  }

  saving.value = true;
  saveError.value = null;
  saveSuccess.value = false;

  try {
    await updateProfile({
      username: username.value.trim() || undefined,
      email: email.value.trim() || undefined,
      currentPassword: currentPassword.value || undefined,
      newPassword: newPassword.value || undefined,
    });
    await checkAuth();
    currentPassword.value = "";
    newPassword.value = "";
    saveSuccess.value = true;
  } catch (err) {
    saveError.value =
      err instanceof Error ? err.message : "Failed to update profile";
  } finally {
    saving.value = false;
  }
}

async function onAvatarFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !currentUser.value) return;

  uploading.value = true;
  uploadError.value = null;

  try {
    await uploadProfilePicture(currentUser.value.id, file);
    avatarFailed.value = false;
    cacheBust.value = Date.now();
  } catch (err) {
    uploadError.value =
      err instanceof Error ? err.message : "Failed to upload picture";
  } finally {
    uploading.value = false;
    // without this, re-picking the same file after a failed upload fires
    // no 'change' event at all (the input's value never actually changed)
    input.value = "";
  }
}
</script>

<template>
  <section class="settings-section">
    <h2>Profile</h2>

    <div class="avatar-row">
      <img
        v-if="!isMock && !avatarFailed"
        :src="avatarUrl"
        alt=""
        class="avatar-image"
        @error="avatarFailed = true"
      />
      <div v-else class="avatar-fallback">
        {{ (currentUser?.username ?? "?").slice(0, 2).toUpperCase() }}
      </div>

      <div class="avatar-meta">
        <div class="avatar-name">{{ currentUser?.username }}</div>
        <div v-if="currentUser?.email" class="avatar-email">
          {{ currentUser.email }}
        </div>
        <label v-if="!isMock" class="upload-label">
          <input
            type="file"
            accept="image/*"
            @change="onAvatarFileChange"
            hidden
          />
          {{ uploading ? "Uploading…" : "Change picture" }}
        </label>
        <p v-if="isMock" class="mock-note">
          Profile pictures aren't available in mock mode.
        </p>
      </div>
    </div>

    <div v-if="uploadError" class="form-error">{{ uploadError }}</div>

    <form @submit.prevent="saveProfile">
      <label class="field">
        <span>Username</span>
        <input v-model="username" type="text" />
      </label>

      <label class="field">
        <span>Email</span>
        <input v-model="email" type="email" />
      </label>

      <label class="field">
        <span>New password (optional)</span>
        <input
          v-model="newPassword"
          type="password"
          autocomplete="new-password"
        />
      </label>

      <label v-if="newPassword" class="field">
        <span>Current password (required to set a new one)</span>
        <input
          v-model="currentPassword"
          type="password"
          autocomplete="current-password"
          required
        />
      </label>

      <div v-if="saveError" class="form-error">{{ saveError }}</div>
      <div v-if="saveSuccess" class="form-success">Profile updated.</div>

      <button type="submit" class="primary-button" :disabled="saving">
        {{ saving ? "Saving…" : "Save changes" }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.settings-section h2 {
  margin: 0 0 16px;
  padding-left: 12px;
  border-left: 3px solid #d68a34;
  font-size: 1rem;
  color: #fff;
}
.avatar-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}
.avatar-image,
.avatar-fallback {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}
.avatar-fallback {
  background: #d68a34;
  color: #111;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 700;
}
.avatar-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.avatar-name {
  color: #fff;
  font-size: 1.05rem;
  font-weight: 700;
}
.avatar-email {
  color: #888;
  font-size: 0.82rem;
  margin-bottom: 4px;
}
.upload-label {
  color: #d68a34;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.upload-label:hover {
  text-decoration: underline;
}
.mock-note {
  color: #777;
  font-size: 13px;
  margin: 0;
}
form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.85rem;
  color: #ccc;
}
.field input {
  background: #111;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  color: #fff;
  padding: 10px 12px;
  font: inherit;
}
.field input:focus {
  outline: none;
  border-color: #d68a34;
}
.form-error {
  color: #fca5a5;
  font-size: 13px;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
}
.form-success {
  color: #86efac;
  font-size: 13px;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
}
.primary-button {
  background: #d68a34;
  color: #111;
  border: none;
  border-radius: 8px;
  padding: 11px;
  font-weight: 600;
  cursor: pointer;
}
.primary-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
