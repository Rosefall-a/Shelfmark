<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchPasswordPolicy, type PasswordPolicy } from "../../services/passwordPolicy";
const policy = ref<PasswordPolicy | null>(null);
const loading = ref(true);
const error = ref("");
onMounted(async () => {
  try { policy.value = await fetchPasswordPolicy(); }
  catch (err) { error.value = err instanceof Error ? err.message : "Failed to load password policy."; }
  finally { loading.value = false; }
});
</script>
<template>
  <section class="settings-section">
    <h2>Password Policy</h2>
    <p class="hint">These rules apply to new local passwords. The policy is deployment-wide and configured through the environment; existing passwords are not changed when the policy changes.</p>
    <p v-if="loading">Loading…</p>
    <p v-else-if="error" class="form-error">{{ error }}</p>
    <ul v-else class="policy-list">
      <li>Minimum length: <strong>{{ policy?.min_length }}</strong></li>
      <li>Uppercase required: <strong>{{ policy?.require_uppercase ? "Yes" : "No" }}</strong></li>
      <li>Lowercase required: <strong>{{ policy?.require_lowercase ? "Yes" : "No" }}</strong></li>
      <li>Number required: <strong>{{ policy?.require_digit ? "Yes" : "No" }}</strong></li>
      <li>Symbol required: <strong>{{ policy?.require_symbol ? "Yes" : "No" }}</strong></li>
    </ul>
    <p class="hint">Change these values with <code>PASSWORD_MIN_LENGTH</code>, <code>PASSWORD_REQUIRE_UPPERCASE</code>, <code>PASSWORD_REQUIRE_LOWERCASE</code>, <code>PASSWORD_REQUIRE_DIGIT</code>, and <code>PASSWORD_REQUIRE_SYMBOL</code>, then restart the application.</p>
  </section>
</template>
<style scoped>
.settings-section { display: flex; flex-direction: column; gap: 16px; }
.hint { color: #999; font-size: 13px; line-height: 1.5; }
.policy-list { margin: 0; padding-left: 20px; color: #ccc; line-height: 1.8; }
code { color: #ddd; }
h2 { margin: 0; color: #fff; }
</style>
