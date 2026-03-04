const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const initReveal = () => {
  const items = document.querySelectorAll(".reveal");
  if (!items.length) return;

  if (prefersReducedMotion) {
    items.forEach((el) => el.classList.add("in-view"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries, obs) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("in-view");
        obs.unobserve(entry.target);
      });
    },
    { threshold: 0.16 }
  );

  items.forEach((el) => observer.observe(el));
};

const initScrollProgress = () => {
  const bar = document.querySelector(".scroll-progress");
  if (!bar) return;

  const update = () => {
    const doc = document.documentElement;
    const top = doc.scrollTop;
    const height = doc.scrollHeight - doc.clientHeight;
    const percent = height > 0 ? (top / height) * 100 : 0;
    bar.style.width = `${percent}%`;
  };

  window.addEventListener("scroll", update, { passive: true });
  update();
};

const initMenu = () => {
  const toggle = document.querySelector(".menu-toggle");
  const nav = document.querySelector(".nav");
  if (!toggle || !nav) return;

  const close = () => {
    nav.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  };

  toggle.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });

  nav.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", close);
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 900) close();
  });
};

const initCopyCitation = () => {
  const button = document.getElementById("copy-citation");
  const code = document.getElementById("citation-code");
  if (!button || !code || !navigator.clipboard) return;

  const original = button.textContent;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(code.textContent.trim());
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = original;
      }, 1200);
    } catch (_) {
      button.textContent = "Failed";
      window.setTimeout(() => {
        button.textContent = original;
      }, 1200);
    }
  });
};

initReveal();
initScrollProgress();
initMenu();
initCopyCitation();
