(() => {
  const storageKey = "job-tracker-theme";
  const root = document.documentElement;
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  const validTheme = (value) => value === "light" || value === "dark";
  let preference = null;

  try {
    const saved = localStorage.getItem(storageKey);
    if (validTheme(saved)) preference = saved;
  } catch {
    // The toggle still works when browser storage is unavailable.
  }

  const applyTheme = () => {
    const theme = preference || (systemTheme.matches ? "dark" : "light");
    root.setAttribute("data-bs-theme", theme);
    document.querySelectorAll(".theme-toggle").forEach((button) => {
      button.setAttribute("aria-pressed", String(theme === "dark"));
      button.title = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
    });
  };

  // Run before styles load so a saved dark theme never flashes light.
  applyTheme();
  systemTheme.addEventListener("change", applyTheme);
  window.addEventListener("storage", (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    preference = validTheme(event.newValue) ? event.newValue : null;
    applyTheme();
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".theme-toggle").forEach((button) => {
      button.hidden = false;
      button.addEventListener("click", () => {
        preference = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
        try {
          localStorage.setItem(storageKey, preference);
        } catch {
          // Keep the selected theme for this page even without storage.
        }
        applyTheme();
      });
    });
    applyTheme();
  });
})();
