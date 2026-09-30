import { createRouter, createWebHistory } from "vue-router";
import { currentUser, authChecked, checkAuth } from "../state/auth";
import { saveLibraryScroll } from "../state/libraryScroll";
import { appearanceLoaded, loadAppearanceSettings } from "../state/appearance";
import { fetchSetupStatus } from "../services/setup";

declare module "vue-router" {
  interface RouteMeta {
    // Shown on the browser tab as "<title> · Archive". Left unset, the
    // tab just falls back to "Archive".
    title?: string;
  }
}

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, _from, savedPosition) {
    if (to.path === "/games") return false;
    if (savedPosition) return savedPosition;
    return { top: 0 };
  },
  routes: [
    {
      path: "/",
      name: "home",
      component: () => import("../views/HomeHub.vue"),
      meta: { title: "Home" },
    },
    {
      path: "/games",
      name: "library",
      component: () => import("../views/GameLibrary.vue"),
      meta: { title: "Games" },
    },
    {
      path: "/collections",
      name: "collections",
      component: () => import("../views/Collections.vue"),
      meta: { title: "Collections" },
    },
    {
      path: "/collections/:name",
      name: "collection-detail",
      component: () => import("../views/CollectionDetail.vue"),
      meta: { title: "Collection" },
    },
    { path: "/upload", redirect: "/settings?section=upload" },
    { path: "/inbox", redirect: "/settings?section=upload" },
    {
      path: "/games/:id",
      name: "game-detail",
      component: () => import("../views/GameDetail.vue"),
      meta: { title: "Game" },
    },
    {
      path: "/movies",
      name: "movie-library",
      component: () => import("../views/MovieLibrary.vue"),
      meta: { title: "Movies" },
    },
    {
      path: "/movies/:id",
      name: "movie-detail",
      component: () => import("../views/MovieDetail.vue"),
      meta: { title: "Movie" },
    },
    {
      path: "/tv",
      name: "tv-show-library",
      component: () => import("../views/TVShowLibrary.vue"),
      meta: { title: "TV" },
    },
    {
      path: "/tv/:id",
      name: "tv-show-detail",
      component: () => import("../views/TVShowDetail.vue"),
      meta: { title: "TV Show" },
    },
    {
      path: "/anime",
      name: "anime-library",
      component: () => import("../views/AnimeLibrary.vue"),
      meta: { title: "Anime" },
    },
    {
      path: "/anime/:id",
      name: "anime-detail",
      component: () => import("../views/AnimeDetail.vue"),
      meta: { title: "Anime" },
    },
    {
      path: "/calendar",
      name: "calendar",
      component: () => import("../views/Calendar.vue"),
      meta: { title: "Calendar" },
    },
    {
      path: "/statistics",
      name: "statistics",
      component: () => import("../views/Statistics.vue"),
      meta: { title: "Statistics" },
    },
    {
      path: "/notifications",
      name: "notifications",
      component: () => import("../views/Notifications.vue"),
      meta: { title: "Notifications" },
    },
    {
      path: "/lists",
      name: "media-lists",
      component: () => import("../views/MediaLists.vue"),
      meta: { title: "Lists" },
    },
    {
      path: "/lists/:id",
      name: "media-list-detail",
      component: () => import("../views/MediaListDetail.vue"),
      meta: { title: "List" },
    },
    // History merged into the Calendar page as a second tab
    { path: "/history", redirect: "/calendar" },
    {
      path: "/login",
      name: "login",
      component: () => import("../views/Login.vue"),
      meta: { title: "Log In" },
    },
    {
      path: "/login/oidcstart",
      name: "oidc-start",
      component: () => import("../views/OidcStart.vue"),
      meta: { title: "Signing in…" },
    },
    {
      path: "/setup",
      name: "setup",
      component: () => import("../views/Setup.vue"),
      meta: { title: "Setup" },
    },
    { path: "/profile", redirect: "/settings" },
    {
      path: "/settings",
      name: "settings",
      component: () => import("../views/Settings.vue"),
      meta: { title: "Settings" },
    },
    {
      path: "/games/:gameId/achievements/:achievementId",
      name: "achievement-detail",
      component: () => import("../views/AchievementDetail.vue"),
      meta: { title: "Achievement" },
    },
    // last, so it only catches addresses no other route claims
    {
      path: "/:pathMatch(.*)*",
      name: "not-found",
      component: () => import("../views/NotFound.vue"),
      meta: { title: "Not Found" },
    },
  ],
});

let setupState: "unknown" | "required" | "complete" | "error" = "unknown";
let startupUiShown = false;

router.beforeEach(async (to, from) => {
  if (from.path === "/games") saveLibraryScroll(window.scrollY);

  if (setupState === "unknown" || setupState === "error") {
    try {
      const status = await fetchSetupStatus();
      setupState = status.setup_required ? "required" : "complete";
      if (
        !status.setup_required &&
        !status.startup_ui_enabled &&
        to.path !== "/setup" &&
        !startupUiShown
      ) {
        startupUiShown = true;
        return { path: "/setup" };
      }
      startupUiShown = true;
    } catch {
      setupState = "error";
    }
  }

  if (setupState === "required" && to.path !== "/setup") {
    try {
      setupState = (await fetchSetupStatus()).setup_required
        ? "required"
        : "complete";
    } catch {
      setupState = "error";
    }
  }

  if (setupState === "required" || setupState === "error") {
    if (to.path !== "/setup")
      return {
        path: "/setup",
      };
    return;
  }
  if (to.path === "/setup") {
    const status = await fetchSetupStatus();
    if (status.setup_required || !status.startup_ui_enabled) {
      startupUiShown = true;
      return;
    }
    return currentUser.value ? "/" : "/login";
  }

  // This public route deliberately bypasses the normal auth redirect so a
  // bookmark or reverse-proxy login entrypoint can start OIDC immediately.
  if (to.path === "/login/oidcstart") return;

  if (!authChecked.value) await checkAuth();
  if (to.path !== "/login" && !currentUser.value) return "/login";
  if (to.path === "/login" && currentUser.value) return "/";
  if (currentUser.value && !appearanceLoaded.value)
    await loadAppearanceSettings();
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Archive` : "Archive";
});

export default router;
