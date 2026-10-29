/*
 * theme.js
 * --------
 * Light/dark mode toggle shared by every page. Light mode is the default
 * (layout.html sets data-theme="light" unless localStorage says otherwise).
 */
(function () {
  const root = document.documentElement;
  const toggleBtn = document.getElementById("theme-toggle");
  if (!toggleBtn) return;

  function syncIcon() {
    const isDark = root.getAttribute("data-theme") === "dark";
    toggleBtn.querySelector(".theme-icon").textContent = isDark ? "\u263D" : "\u2600";
  }

  toggleBtn.addEventListener("click", () => {
    const isDark = root.getAttribute("data-theme") === "dark";
    const next = isDark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    localStorage.setItem("dptlite-theme", next);
    syncIcon();
  });

  syncIcon();
})();
