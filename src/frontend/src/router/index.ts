import { createRouter, createWebHistory } from "vue-router";
import { currentUser, authChecked, checkAuth } from "../state/auth";
import { saveLibraryScroll } from "../state/libraryScroll";
import { appearanceLoaded, loadAppearanceSettings } from "../state/appearance";
import { fetchSetupStatus } from "../services/setup";

declare module "vue-router" {
  interface RouteMeta {
    // the browser tab title, see state/pageTitle.ts
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
      meta: { title: "Home" },
      component: () => import("../views/HomeHub.vue"),
    },
    {
      path: "/games",
      name: "library",
      meta: { title: "Games" },
      component: () => import("../views/GameLibrary.vue"),
    },
    {
      path: "/collections",
      name: "collections",
      meta: { title: "Collections" },
      component: () => import("../views/Collections.vue"),
    },
    {
      path: "/collections/:name",
      name: "collection-detail",
      meta: { title: "Collection" },
      component: () => import("../views/CollectionDetail.vue"),
    },
    {
      path: "/inbox",
      name: "inbox",
      meta: { title: "Inbox" },
      component: () => import("../views/Inbox.vue"),
    },
    {
      path: "/bounties",
      name: "bounties",
      meta: { title: "Bounties" },
      component: () => import("../views/Bounties.vue"),
    },
    {
      path: "/games/:id",
      name: "game-detail",
      meta: { title: "Game" },
      component: () => import("../views/GameDetail.vue"),
    },
    {
      path: "/cards",
      name: "card-collection",
      meta: { title: "Cards" },
      component: () => import("../views/CardCollection.vue"),
    },
    {
      path: "/cards/:cardId",
      name: "card-detail",
      meta: { title: "Card" },
      component: () => import("../views/CardDetail.vue"),
    },
    {
      path: "/sets",
      name: "set-list",
      meta: { title: "Sets" },
      component: () => import("../views/SetList.vue"),
    },
    {
      path: "/sets/:id",
      name: "set-detail",
      meta: { title: "Set" },
      component: () => import("../views/SetDetail.vue"),
    },
    {
      path: "/movies",
      name: "movie-library",
      meta: { title: "Movies" },
      component: () => import("../views/MovieLibrary.vue"),
    },
    {
      path: "/movies/:id",
      name: "movie-detail",
      meta: { title: "Movie" },
      component: () => import("../views/MovieDetail.vue"),
    },
    {
      path: "/tv",
      name: "tv-show-library",
      meta: { title: "TV Shows" },
      component: () => import("../views/TVShowLibrary.vue"),
    },
    {
      path: "/tv/:id",
      name: "tv-show-detail",
      meta: { title: "TV Show" },
      component: () => import("../views/TVShowDetail.vue"),
    },
    {
      path: "/anime",
      name: "anime-library",
      meta: { title: "Anime" },
      component: () => import("../views/AnimeLibrary.vue"),
    },
    {
      path: "/anime/:id",
      name: "anime-detail",
      meta: { title: "Anime" },
      component: () => import("../views/AnimeDetail.vue"),
    },
    {
      path: "/calendar",
      name: "calendar",
      meta: { title: "Calendar" },
      component: () => import("../views/Calendar.vue"),
    },
    {
      path: "/statistics",
      name: "statistics",
      meta: { title: "Statistics" },
      component: () => import("../views/Statistics.vue"),
    },
    {
      path: "/notifications",
      name: "notifications",
      meta: { title: "Notifications" },
      component: () => import("../views/Notifications.vue"),
    },
    {
      path: "/lists",
      name: "media-lists",
      meta: { title: "Lists" },
      component: () => import("../views/MediaLists.vue"),
    },
    {
      path: "/lists/:id",
      name: "media-list-detail",
      meta: { title: "List" },
      component: () => import("../views/MediaListDetail.vue"),
    },
    // History merged into the Calendar page as a second tab
    { path: "/history", redirect: "/calendar" },
    {
      path: "/login",
      name: "login",
      meta: { title: "Sign in" },
      component: () => import("../views/Login.vue"),
    },
    {
      path: "/login/oidcstart",
      name: "oidc-start",
      meta: { title: "Sign in" },
      component: () => import("../views/OidcStart.vue"),
    },
    {
      path: "/setup",
      name: "setup",
      meta: { title: "Setup" },
      component: () => import("../views/Setup.vue"),
    },
    { path: "/profile", redirect: "/settings" },
    {
      path: "/settings",
      name: "settings",
      meta: { title: "Settings" },
      component: () => import("../views/Settings.vue"),
    },
    {
      path: "/games/:gameId/achievements/:achievementId",
      name: "achievement-detail",
      meta: { title: "Achievement" },
      component: () => import("../views/AchievementDetail.vue"),
    },
    // last, so it only catches addresses no other route claims
    {
      path: "/:pathMatch(.*)*",
      name: "not-found",
      meta: { title: "Page not found" },
      component: () => import("../views/NotFound.vue"),
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
      if (!status.setup_required && !status.startup_ui_enabled && to.path !== "/setup" && !startupUiShown) {
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
    if (status.setup_required || !status.startup_ui_enabled) { startupUiShown = true; return; }
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

export default router;
