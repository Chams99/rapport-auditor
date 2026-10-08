// Applies a saved theme before first paint so the page never flashes the wrong colours.
(() => {
  try {
    const saved = localStorage.getItem("ra-theme");
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  } catch {
    // Storage can be unavailable (private mode, blocked site data); the system theme applies.
  }
})();
