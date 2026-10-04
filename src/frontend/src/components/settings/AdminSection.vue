<script setup lang="ts">
import { ref, onMounted } from "vue";
import { currentUser } from "../../state/auth";
import {
  listUsers,
  createUser,
  deleteUser,
  setUserAdmin,
} from "../../services/admin";
import ToggleButton from "./ToggleButton.vue";
import PasswordInput from "../PasswordInput.vue";
import type { AdminUser } from "../../services/admin";
import PasswordRequirements from "./PasswordRequirements.vue";
import { fetchPasswordPolicy, passwordValidationErrors, type PasswordPolicy } from "../../services/passwordPolicy";

const users = ref<AdminUser[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const passwordPolicy = ref<PasswordPolicy | null>(null);

async function loadUsers() {
  loading.value = true;
  error.value = null;
  try {
    users.value = await listUsers();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load users";
  } finally {
    loading.value = false;
  }
}
onMounted(async () => {
  await Promise.all([
    loadUsers(),
    fetchPasswordPolicy().then((policy) => { passwordPolicy.value = policy; }).catch((err) => {
      error.value = err instanceof Error ? err.message : "Failed to load password policy";
    }),
  ]);
});

const showCreateForm = ref(false);
const newUsername = ref("");
const newEmail = ref("");
const newPassword = ref("");
const confirmPassword = ref("");
const newIsAdmin = ref(false);
const creating = ref(false);
const createError = ref<string | null>(null);

async function handleCreateUser() {
  const validationErrors = passwordPolicy.value
    ? passwordValidationErrors(newPassword.value, passwordPolicy.value)
    : ["Password requirements could not be loaded."];
  if (validationErrors.length) {
    createError.value = validationErrors[0];
    return;
  }
  if (!newPassword.value || newPassword.value !== confirmPassword.value) {
    createError.value = "The passwords do not match.";
    return;
  }
  creating.value = true;
  createError.value = null;
  try {
    await createUser({
      username: newUsername.value.trim(),
      email: newEmail.value.trim(),
      password: newPassword.value,
      isAdmin: newIsAdmin.value,
    });
    newUsername.value = "";
    newEmail.value = "";
    newPassword.value = "";
    confirmPassword.value = "";
    newIsAdmin.value = false;
    showCreateForm.value = false;
    await loadUsers();
  } catch (err) {
    createError.value =
      err instanceof Error ? err.message : "Failed to create user";
  } finally {
    creating.value = false;
  }
}

const deletingUser = ref<AdminUser | null>(null);
const deleting = ref(false);
const deleteError = ref<string | null>(null);
async function confirmDeleteUser() {
  if (!deletingUser.value) return;
  deleting.value = true;
  deleteError.value = null;
  try {
    await deleteUser(deletingUser.value.id);
    deletingUser.value = null;
    await loadUsers();
  } catch (err) {
    deleteError.value =
      err instanceof Error ? err.message : "Failed to delete user";
  } finally {
    deleting.value = false;
  }
}

const togglingAdminId = ref<string | null>(null);
async function toggleAdmin(user: AdminUser) {
  togglingAdminId.value = user.id;
  try {
    const updated = await setUserAdmin(user.id, !user.is_admin);
    const index = users.value.findIndex((u) => u.id === user.id);
    if (index !== -1) users.value[index] = updated;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to update user";
  } finally {
    togglingAdminId.value = null;
  }
}

function openCreateForm() {
  newUsername.value = "";
  newEmail.value = "";
  newPassword.value = "";
  confirmPassword.value = "";
  newIsAdmin.value = false;
  createError.value = null;
  showCreateForm.value = true;
}
</script>

<template>
  <section class="settings-section">
    <h2>Users</h2>
    <p class="section-hint">
      Manage the accounts on this server, including administrator access.
    </p>
    <p v-if="loading">Loading…</p>
    <p v-else-if="error" class="form-error">{{ error }}</p>
    <template v-else>
      <table class="user-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Email</th>
            <th>Role</th>
            <th>Joined</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>{{ user.username }}</td>
            <td>{{ user.email }}</td>
            <td>
              <span class="role-badge" :class="{ admin: user.is_admin }">{{
                user.is_admin ? "Admin" : "User"
              }}</span>
            </td>
            <td class="joined">
              {{
                user.created_at
                  ? new Date(user.created_at * 1000).toLocaleDateString()
                  : "N/A"
              }}
            </td>
            <td class="actions">
              <button
                type="button"
                class="small-button"
                :disabled="
                  user.id === currentUser?.id || togglingAdminId === user.id
                "
                @click="toggleAdmin(user)"
              >
                {{ user.is_admin ? "Demote" : "Promote" }}
              </button>
              <button
                type="button"
                class="small-button danger"
                :disabled="user.id === currentUser?.id"
                @click="
                  deletingUser = user;
                  deleteError = null;
                "
              >
                Delete
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <button
        type="button"
        class="secondary-button"
        @click="showCreateForm ? (showCreateForm = false) : openCreateForm()"
      >
        {{ showCreateForm ? "Cancel" : "+ Create user" }}
      </button>
      <form
        v-if="showCreateForm"
        class="create-form"
        @submit.prevent="handleCreateUser"
      >
        <label class="field"
          ><span>Username</span
          ><input v-model="newUsername" type="text" required
        /></label>
        <label class="field"
          ><span>Email</span><input v-model="newEmail" type="email" required
        /></label>
        <label class="field"
          ><span>Password</span
          ><PasswordInput
            v-model="newPassword"
            mode="new"
            autocomplete="new-password"
            :required="true"
          /></label>
        <PasswordRequirements v-if="passwordPolicy" :password="newPassword" :policy="passwordPolicy" />
        <label class="field"
          ><span>Confirm password</span
          ><PasswordInput
            v-model="confirmPassword"
            mode="new"
            autocomplete="new-password"
            :required="true"
          /></label>
        <ToggleButton v-model="newIsAdmin" label="Grant admin access"
          >Grant admin access</ToggleButton
        >
        <div v-if="createError" class="form-error">{{ createError }}</div>
        <button type="submit" class="primary-button" :disabled="creating">
          {{ creating ? "Creating…" : "Create user" }}
        </button>
      </form>
    </template>
    <div
      v-if="deletingUser"
      class="confirm-backdrop"
      @click.self="deletingUser = null"
    >
      <div class="confirm-dialog">
        <h3>Delete {{ deletingUser.username }}?</h3>
        <p>This can't be undone: their data folder is removed too.</p>
        <div v-if="deleteError" class="form-error">{{ deleteError }}</div>
        <div class="confirm-actions">
          <button
            type="button"
            class="secondary-button"
            @click="deletingUser = null"
          >
            Cancel</button
          ><button
            type="button"
            class="danger-button"
            :disabled="deleting"
            @click="confirmDeleteUser"
          >
            {{ deleting ? "Deleting…" : "Delete" }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.settings-section h2 {
  margin: 0 0 8px;
  padding-left: 12px;
  border-left: 3px solid #d68a34;
  font-size: 1rem;
  color: #fff;
}
.section-hint {
  color: #999;
  font-size: 0.82rem;
  line-height: 1.6;
  margin: 0 0 16px;
}
.user-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 16px;
  font-size: 0.85rem;
}
.user-table th {
  text-align: left;
  color: #777;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0 10px 8px;
  border-bottom: 1px solid #2a2a2a;
}
.user-table td {
  padding: 10px;
  border-bottom: 1px solid #232323;
  color: #ccc;
}
.role-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  color: #999;
  background: rgba(255, 255, 255, 0.06);
}
.role-badge.admin {
  color: #d68a34;
  background: rgba(214, 138, 52, 0.14);
}
.joined {
  color: #999;
  font-size: 0.8rem;
}
.actions {
  display: flex;
  gap: 6px;
}
.small-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.small-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.small-button.danger {
  color: #fca5a5;
}
.secondary-button {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-weight: 600;
  cursor: pointer;
}
.create-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #2a2a2a;
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
.form-error {
  color: #fca5a5;
  font-size: 13px;
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.3);
  border-radius: 8px;
  padding: 8px 10px;
}
.confirm-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}
.confirm-dialog {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 22px;
  max-width: 360px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}
.confirm-dialog h3 {
  margin: 0 0 8px;
  color: #fff;
}
.confirm-dialog p {
  margin: 0 0 18px;
  color: #999;
  font-size: 0.85rem;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.danger-button {
  background: rgba(220, 38, 38, 0.18);
  color: #fca5a5;
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-weight: 600;
  cursor: pointer;
}
.danger-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
