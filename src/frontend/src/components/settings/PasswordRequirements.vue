<script setup lang="ts">
import { computed } from "vue";
import type { PasswordPolicy } from "../../services/passwordPolicy";

const props = defineProps<{ password: string; policy: PasswordPolicy }>();
const requirements = computed(() => [
  { label: `At least ${props.policy.min_length} characters`, key: "length" },
  ...(props.policy.require_uppercase ? [{ label: "An uppercase letter", key: "uppercase" }] : []),
  ...(props.policy.require_lowercase ? [{ label: "A lowercase letter", key: "lowercase" }] : []),
  ...(props.policy.require_digit ? [{ label: "A number", key: "digit" }] : []),
  ...(props.policy.require_symbol ? [{ label: "A symbol", key: "symbol" }] : []),
]);
function met(key: string): boolean {
  if (!props.password) return false;
  if (key === "length") return props.password.length >= props.policy.min_length;
  if (key === "uppercase") return /[A-Z]/.test(props.password);
  if (key === "lowercase") return /[a-z]/.test(props.password);
  if (key === "digit") return /\d/.test(props.password);
  if (key === "symbol") return /[^A-Za-z0-9]/.test(props.password);
  return false;
}
</script>
<template>
  <div class="password-requirements" aria-live="polite">
    <span class="requirements-title">Password requirements</span>
    <ul>
      <li v-for="requirement in requirements" :key="requirement.key" :class="{ met: met(requirement.key) }">
        <span aria-hidden="true">{{ met(requirement.key) ? "✓" : "•" }}</span>
        {{ requirement.label }}
      </li>
    </ul>
  </div>
</template>
<style scoped>
.password-requirements { color: #999; font-size: 12px; line-height: 1.5; }
.requirements-title { color: #bbb; font-weight: 600; }
ul { list-style: none; margin: 6px 0 0; padding: 0; }
li { color: #dca1a1; }
li.met { color: #86efac; }
li span { display: inline-block; width: 16px; }
</style>
