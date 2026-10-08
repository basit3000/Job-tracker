const headerTools = document.getElementById("headerTools");
const menuToggle = document.querySelector(".header-menu-toggle");

// A simple disclosure responds immediately to touch, keyboard, and resizing.
if (headerTools && menuToggle) {
  const desktop = window.matchMedia("(min-width: 768px)");
  const setOpen = (open) => {
    headerTools.classList.toggle("show", open);
    menuToggle.setAttribute("aria-expanded", String(open));
  };
  menuToggle.addEventListener("click", () => {
    setOpen(menuToggle.getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !desktop.matches && headerTools.classList.contains("show")) {
      setOpen(false);
      menuToggle.focus();
    }
  });
  desktop.addEventListener("change", () => {
    const focusWasInside = headerTools.contains(document.activeElement);
    setOpen(false);
    headerTools.querySelectorAll('[data-bs-toggle="dropdown"]').forEach((button) => {
      window.bootstrap?.Dropdown.getInstance(button)?.hide();
    });
    if (focusWasInside) {
      (desktop.matches ? document.getElementById("accountToggle") : menuToggle).focus();
    }
  });
}
