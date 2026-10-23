/* Magnit — umumiy skriptlar: mavzu, menyu, animatsiyalar, AI-chat */
(function () {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const fmt = (n) => Math.round(Number(n) || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const csrf = () => {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : ($("[name=csrfmiddlewaretoken]") || {}).value || "";
  };
  const parseNum = (s) => Number(String(s).replace(/[^\d]/g, "")) || 0;
  window.Magnit = { fmt, csrf, parseNum, $, $$ };

  /* --- Mavzu (yorug'/qorong'i) --- */
  const root = document.documentElement;
  const isDark = () => root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const themeBtn = $("#theme-toggle");
  const paintThemeIcon = () => {
    if (themeBtn) themeBtn.innerHTML = `<svg><use href="#i-${isDark() ? "sun" : "moon"}"/></svg>`;
  };
  paintThemeIcon();
  themeBtn && themeBtn.addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
    // Kirgan foydalanuvchi tanlovi profilga ham yoziladi (Kabinet → Sozlamalar bilan bir xil)
    if (themeBtn.dataset.saveUrl) {
      fetch(themeBtn.dataset.saveUrl, { method: "POST", headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" }, body: "theme=" + root.dataset.theme });
    }
    paintThemeIcon();
    document.dispatchEvent(new CustomEvent("themechange"));
  });

  /* --- Mobil menyu --- */
  const menuBtn = $("#menu-btn"), menu = $("#mobile-menu");
  menuBtn && menuBtn.addEventListener("click", () => {
    const open = menu.classList.toggle("open");
    menuBtn.setAttribute("aria-expanded", open);
  });

  /* --- Ochiladigan menyular (sensorli ekran va klaviatura uchun) --- */
  const dropdowns = $$(".dropdown");
  const closeDropdowns = (except) => dropdowns.forEach((d) => {
    if (d === except) return;
    d.classList.remove("open");
    $(".dd-toggle", d).setAttribute("aria-expanded", "false");
  });
  dropdowns.forEach((d) => $(".dd-toggle", d).addEventListener("click", (e) => {
    e.stopPropagation();
    closeDropdowns(d);
    $(".dd-toggle", d).setAttribute("aria-expanded", d.classList.toggle("open"));
  }));
  document.addEventListener("click", () => closeDropdowns());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDropdowns(); });

  /* --- Toastlar --- */
  $$(".toasts .alert").forEach((el, i) => setTimeout(() => {
    el.style.transition = "opacity .4s, transform .4s"; el.style.opacity = "0"; el.style.transform = "translateY(-8px)";
    setTimeout(() => el.remove(), 400);
  }, 5000 + i * 600));

  // Panjaralardagi elementlar ketma-ket paydo bo'ladi
  $$(".grid-2, .grid-3, .grid-4, .stats-band, .steps").forEach((g) =>
    Array.from(g.children).forEach((el, i) => { el.classList.add("reveal"); el.style.setProperty("--d", `${i * 90}ms`); }));
  /* --- Ko'rinishga kirganda animatsiya va hisoblagichlar --- */
  const countUp = (el) => {
    const target = Number(el.dataset.count), dur = 1400, t0 = performance.now(), suffix = el.dataset.suffix || "";
    const step = (t) => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * e) + suffix;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => entries.forEach((en) => {
      if (!en.isIntersecting) return;
      en.target.classList.add("in");
      if (en.target.dataset.count) countUp(en.target);
      io.unobserve(en.target);
    }), { threshold: 0.15 });
    $$(".reveal, [data-count]").forEach((el) => io.observe(el));
  } else {
    $$(".reveal").forEach((el) => el.classList.add("in"));
  }

  /* --- Raqamli maydonlarni bo'shliq bilan formatlash --- */
  $$("input[data-money]").forEach((inp) => {
    inp.addEventListener("input", () => {
      const pos = inp.value.length - inp.selectionStart;
      inp.value = inp.value.replace(/[^\d]/g, "") ? fmt(parseNum(inp.value)) : "";
      inp.setSelectionRange(inp.value.length - pos, inp.value.length - pos);
    });
  });

  /* --- Animatsiyalar --- */
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = matchMedia("(pointer: fine)").matches;


  // Hero sarlavhasi so'zma-so'z
  $$("[data-split]").forEach((el) => {
    let i = 0;
    const walk = (node) => Array.from(node.childNodes).forEach((n) => {
      if (n.nodeType === 3) {
        const frag = document.createDocumentFragment();
        n.textContent.split(/(\s+)/).forEach((part) => {
          if (!part) return;
          if (/^\s+$/.test(part)) return frag.append(part);
          const s = document.createElement("span");
          s.className = "w"; s.style.setProperty("--i", i++); s.textContent = part;
          frag.append(s);
        });
        n.replaceWith(frag);
      } else if (n.nodeType === 1 && n.classList.contains("gradient-text")) {
        n.classList.add("w"); n.style.setProperty("--i", i++);
      } else if (n.nodeType === 1) walk(n);
    });
    walk(el);
    el.classList.add("split-words");
  });

  // Sahifa o'qish progressi
  const progress = $(".scroll-progress");
  const onScroll = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    progress && progress.style.setProperty("--progress", max > 0 ? scrollY / max : 0);
  };
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  if (finePointer && !reduceMotion) {
    // Fon yorug'ligi va kartalardagi yorug'lik sichqonchaga ergashadi
    let raf = 0, mx = 0, my = 0;
    addEventListener("pointermove", (e) => {
      mx = e.clientX; my = e.clientY;
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        root.style.setProperty("--mx", mx + "px");
        root.style.setProperty("--my", my + "px");
        document.body.classList.add("has-pointer");
      });
    }, { passive: true });
    document.addEventListener("pointermove", (e) => {
      const card = e.target.closest && e.target.closest(".card");
      if (!card) return;
      const r = card.getBoundingClientRect();
      card.style.setProperty("--cx", `${e.clientX - r.left}px`);
      card.style.setProperty("--cy", `${e.clientY - r.top}px`);
    }, { passive: true });

    // 3D egilish
    $$("[data-tilt]").forEach((el) => {
      el.classList.add("tilt");
      el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
        el.style.setProperty("--ry", `${x * 10}deg`);
        el.style.setProperty("--rx", `${-y * 10}deg`);
      });
      el.addEventListener("pointerleave", () => { el.style.setProperty("--rx", "0deg"); el.style.setProperty("--ry", "0deg"); });
    });
  }

  // Fon zarrachalari: sekin suzuvchi nuqtalar, yaqinlari ingichka chiziq bilan bog'lanadi
  const canvas = $("#bg-particles");
  if (canvas && !reduceMotion) {
    const ctx = canvas.getContext("2d");
    let w, h, dpr, pts = [], running = true;
    const resize = () => {
      dpr = Math.min(devicePixelRatio || 1, 2);
      w = canvas.width = innerWidth * dpr; h = canvas.height = innerHeight * dpr;
      const n = Math.round(Math.min(70, (innerWidth * innerHeight) / 22000));
      pts = Array.from({ length: n }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.18 * dpr, vy: (Math.random() - 0.5) * 0.18 * dpr - 0.05 * dpr,
        r: (Math.random() * 1.4 + 0.6) * dpr,
      }));
    };
    const tick = () => {
      if (!running) return;
      ctx.clearRect(0, 0, w, h);
      const dark = isDark(), dot = dark ? "125,211,252" : "14,116,144", link = 120 * dpr;
      for (const p of pts) {
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x = w; if (p.x > w) p.x = 0; if (p.y < 0) p.y = h; if (p.y > h) p.y = 0;
      }
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i];
        for (let j = i + 1; j < pts.length; j++) {
          const b = pts[j], dx = a.x - b.x, dy = a.y - b.y, dist = Math.hypot(dx, dy);
          if (dist < link) {
            ctx.strokeStyle = `rgba(${dot},${(1 - dist / link) * (dark ? 0.18 : 0.12)})`;
            ctx.lineWidth = dpr * 0.6;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
        ctx.fillStyle = `rgba(${dot},${dark ? 0.55 : 0.35})`;
        ctx.beginPath(); ctx.arc(a.x, a.y, a.r, 0, Math.PI * 2); ctx.fill();
      }
      requestAnimationFrame(tick);
    };
    resize();
    addEventListener("resize", resize);
    document.addEventListener("visibilitychange", () => {
      running = !document.hidden;
      if (running) requestAnimationFrame(tick);
    });
    requestAnimationFrame(tick);
  }

  /* --- Telefon raqam: "90 123 45 67" ko'rinishida formatlash --- */
  const fmtPhone = (v) => {
    let d = String(v).replace(/\D/g, "");
    if (d.length > 9 && d.startsWith("998")) d = d.slice(3);
    d = d.slice(0, 9);
    return [d.slice(0, 2), d.slice(2, 5), d.slice(5, 7), d.slice(7, 9)].filter(Boolean).join(" ");
  };
  $$("input[data-phone]").forEach((inp) => {
    if (inp.value) inp.value = fmtPhone(inp.value);
    inp.addEventListener("input", () => { inp.value = fmtPhone(inp.value); });
  });

  /* --- Parolni ko'rsatish/yashirish --- */
  $$("[data-pw-toggle]").forEach((btn) => btn.addEventListener("click", () => {
    const inp = document.getElementById(btn.dataset.pwToggle), show = inp.type === "password";
    inp.type = show ? "text" : "password";
    inp.toggleAttribute("data-pw", show);
    btn.innerHTML = `<svg><use href="#i-${show ? "eye-off" : "eye"}"/></svg>`;
    btn.setAttribute("aria-label", show ? "Parolni yashirish" : "Parolni ko'rsatish");
  }));

  /* --- AI-chat --- */
  const panel = $("#chat-panel");
  if (!panel) return;
  const fab = $("#chat-fab"), body = $("#chat-body"), form = $("#chat-form"), input = $("#chat-input");

  const toggleChat = (open) => {
    panel.classList.toggle("open", open);
    fab.setAttribute("aria-expanded", open);
    fab.innerHTML = `<svg><use href="#i-${open ? "x" : "chat"}"/></svg>`;
    if (open) setTimeout(() => input.focus(), 200);
  };
  fab.addEventListener("click", () => toggleChat(!panel.classList.contains("open")));
  $("#chat-close").addEventListener("click", () => toggleChat(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleChat(false); });
  $$("[data-open-chat]").forEach((b) => b.addEventListener("click", (e) => {
    e.preventDefault(); toggleChat(true);
    if (b.dataset.openChat) send(b.dataset.openChat);
  }));

  const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<em>$2</em>")
    .replace(/(^|\W)_(.+?)_(?=\W|$)/g, "$1<em>$2</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(((?:\/|https?:\/\/)[^)\s]*)\)/g, (m, t, u) => `<a href="${u}"${u.startsWith("http") ? ' target="_blank" rel="noopener"' : ""}>${t}</a>`);

  // Xavfsiz mini-markdown: avval HTML ekranlanadi, so'ng cheklangan teglar qo'shiladi.
  const md = (text) => {
    const lines = escapeHtml(text).split(/\n/);
    let html = "", list = null;
    const close = () => { if (list) { html += `</${list}>`; list = null; } };
    for (const raw of lines) {
      const line = raw.trim();
      let m;
      if ((m = line.match(/^[-*•]\s+(.*)/))) { if (list !== "ul") { close(); html += "<ul>"; list = "ul"; } html += `<li>${inline(m[1])}</li>`; }
      else if ((m = line.match(/^\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); html += "<ol>"; list = "ol"; } html += `<li>${inline(m[1])}</li>`; }
      else if (!line) { close(); }
      else if ((m = line.match(/^#{1,4}\s+(.*)/))) { close(); html += `<p><strong>${inline(m[1])}</strong></p>`; }
      else { close(); html += `<p>${inline(line)}</p>`; }
    }
    close();
    return html;
  };

  const addMsg = (text, who) => {
    const el = document.createElement("div");
    el.className = `msg ${who}`;
    if (who === "bot") el.innerHTML = md(text); else el.textContent = text;
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
    return el;
  };

  let busy = false;
  async function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true;
    addMsg(text, "user");
    input.value = "";
    const typing = document.createElement("div");
    typing.className = "msg bot typing";
    typing.innerHTML = "<span></span><span></span><span></span>";
    body.appendChild(typing);
    body.scrollTop = body.scrollHeight;
    try {
      const res = await fetch(panel.dataset.url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      typing.remove();
      addMsg(data.reply || data.error || panel.dataset.errGeneric, "bot");
    } catch (e) {
      typing.remove();
      addMsg(panel.dataset.errNetwork, "bot");
    } finally {
      busy = false;
    }
  }
  window.Magnit.openChat = (t) => { toggleChat(true); if (t) send(t); };

  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  $$("#chat-suggest button").forEach((b) => b.addEventListener("click", () => send(b.textContent)));
  $("#chat-reset").addEventListener("click", async () => {
    await fetch(panel.dataset.resetUrl, { method: "POST", headers: { "X-CSRFToken": csrf() } });
    $$(".msg", body).slice(1).forEach((m) => m.remove());
  });
})();
