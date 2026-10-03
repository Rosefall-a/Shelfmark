// For CSS that reveals something on `:hover, :focus-within` (hover-expand
// menus, row action buttons that appear on hover). Focus alone keeps
// `:focus-within` true, so clicking one of the revealed controls and then
// moving the mouse away leaves it stuck visible — it takes an unrelated
// click elsewhere to move focus away before it can close. Wiring this to
// `@mouseleave` on the hover container closes that gap: focus no longer
// outlives the hover once the pointer has actually left.
export function blurOnLeave(e: MouseEvent): void {
  const container = e.currentTarget as HTMLElement | null;
  const active = document.activeElement as HTMLElement | null;
  if (container && active && container.contains(active)) active.blur();
}
