import { createRouter, createWebHistory } from "vue-router";
import { currentUser, authChecked, authCheckFailed, checkAuth } from "../state/auth";
import { saveLibraryScroll } from "../state/libraryScroll";
import { appearanceLoaded, loadAppearanceSettings } from "../state/appearance";
import { fetchSetupStatus } from "../services/setup";
import {
  classifySetupStatus,
  rememberReturnPath,
  safeReturnPath,
  setStartupState,
} from "../state/startup";

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
    { path: "/upload", redirect: "/settings?section=upload" },
    { path: "/inbox", redirect: "/settings?section=upload" },
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

let setupState: "unknown" | "required" | "complete" = "unknown";
let startupUiShown = false;

function loginRedirect(toPath: string) {
  const returnPath = rememberReturnPath(toPath);
  return returnPath
    ? { path: "/login", query: { return_to: returnPath } }
    : { path: "/login" };
}

function setupRedirect(toPath: string) {
  const returnPath = rememberReturnPath(toPath);
  return returnPath
    ? { path: "/setup", query: { return_to: returnPath } }
    : { path: "/setup" };
}

router.beforeEach(async (to, from) => {
  if (from.path === "/games") saveLibraryScroll(window.scrollY);

  if (setupState === "unknown") {
    setStartupState("checking");
    try {
      const status = await fetchSetupStatus();
      const state = classifySetupStatus(status);
      setupState = state === "setup-required" ? "required" : "complete";
      if (state === "setup-required") {
        setStartupState("setup-required");
      } else if (!status.startup_ui_enabled && to.path !== "/setup" && !startupUiShown) {
        startupUiShown = true;
        return setupRedirect(to.fullPath);
      } else {
        startupUiShown = true;
      }
    } catch (err) {
      setStartupState(
        "unavailable",
        err instanceof Error ? err.message : "Unable to reach the backend.",
      );
      return false;
    }
  }

  if (setupState === "required" && to.path !== "/setup") {
    setStartupState("setup-required");
    try {
      const status = await fetchSetupStatus();
      if (!status.setup_required) {
        setupState = "complete";
      }
    } catch (err) {
      setStartupState(
        "unavailable",
        err instanceof Error ? err.message : "Unable to reach the backend.",
      );
      return false;
    }
  }

  if (setupState === "required") {
    if (to.path !== "/setup") return setupRedirect(to.fullPath);
    return;
  }

  if (to.path === "/setup") {
    try {
      const status = await fetchSetupStatus();
      if (status.setup_required) {
        setStartupState("setup-required");
        return;
      }
      setupState = "complete";
      const returnPath = safeReturnPath(to.query.return_to);
      if (!authChecked.value) await checkAuth();
      if (currentUser.value) {
        setStartupState("ready");
        return returnPath ?? "/";
      }
      setStartupState("auth-required");
      return returnPath
        ? { path: "/login", query: { return_to: returnPath } }
        : "/login";
    } catch (err) {
      setStartupState(
        "unavailable",
        err instanceof Error ? err.message : "Unable to reach the backend.",
      );
      return false;
    }
  }

  // This public route deliberately bypasses the normal auth redirect so a
  // bookmark or reverse-proxy login entrypoint can start OIDC immediately.
  if (to.path === "/login/oidcstart") return;

  if (!authChecked.value) await checkAuth();
  if (authCheckFailed.value) {
    setStartupState("unavailable", "Unable to reach the backend while checking authentication.");
    return false;
  }

  if (to.path !== "/login" && !currentUser.value) {
    setStartupState("auth-required");
    return loginRedirect(to.fullPath);
  }

  if (to.path === "/login" && currentUser.value) {
    setStartupState("ready");
    return safeReturnPath(to.query.return_to) ?? "/";
  }

  if (currentUser.value) {
    setStartupState("ready");
    if (!appearanceLoaded.value) await loadAppearanceSettings();
  } else {
    setStartupState("auth-required");
  }
});

export default router;
