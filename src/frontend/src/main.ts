import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import { openPluginDialog } from "./state/pluginExtensions";
import { configureNativePluginHost } from "./state/pluginNative";
import "./style.css";
import "./styles/ui.css";

document.documentElement.classList.toggle(
  "compact",
  localStorage.getItem("compactMode") === "true",
);
document.documentElement.classList.toggle(
  "high-contrast",
  localStorage.getItem("highContrastMode") === "true",
);

configureNativePluginHost(router, openPluginDialog);
createApp(App).use(router).mount("#app");
