<script setup lang="ts">
import { onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { startOidcLogin } from "../services/oidc";

const route = useRoute();
const router = useRouter();

onMounted(() => {
  const provider = typeof route.params.provider === "string" ? route.params.provider.trim() : "";
  if (!provider || provider === "local" || provider === "oidcstart") {
    router.replace("/login");
    return;
  }
  startOidcLogin(provider);
});
</script>
<template><main class="oidc-start" aria-live="polite"><span>Starting sign-in…</span></main></template>
<style scoped>
.oidc-start{min-height:100vh;display:grid;place-items:center;background:#121212;color:#999;font-family:system-ui,sans-serif;font-size:13px}
</style>