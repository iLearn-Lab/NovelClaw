(function () {
  const sidebar = document.getElementById("workspace-navigation");
  const toggle = document.querySelector("[data-mobile-nav-toggle]");
  const overlay = document.querySelector("[data-mobile-nav-close]");
  if (!sidebar || !toggle || !overlay) return;
  const mobile = window.matchMedia("(max-width: 800px)");
  let open = false;

  function apply(next, restoreFocus = false) {
    open = mobile.matches && next;
    document.body.classList.toggle("mobile-nav-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    sidebar.inert = mobile.matches && !open;
    if (open) sidebar.querySelector("a, button")?.focus();
    else if (restoreFocus) toggle.focus();
  }

  toggle.addEventListener("click", () => apply(!open));
  overlay.addEventListener("click", () => apply(false, true));
  sidebar.addEventListener("click", (event) => {
    if (mobile.matches && event.target.closest("a, [data-sidebar-toggle]")) apply(false, true);
  });
  document.addEventListener("keydown", (event) => {
    if (!open) return;
    if (event.key === "Escape") apply(false, true);
    if (event.key === "Tab") {
      const focusable = [...sidebar.querySelectorAll("a, button, summary, input, select, textarea")]
        .filter((node) => !node.disabled && node.getClientRects().length);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  mobile.addEventListener("change", () => apply(false));
  apply(false);
})();
