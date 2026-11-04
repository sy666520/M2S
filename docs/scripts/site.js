/* music2score 站点交互：导航、滚动进场、标签切换、图片放大、命令复制。
   无依赖，所有页面共用。 */
(function () {
  "use strict";

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 年份 ---------- */
  var year = document.getElementById("year");
  if (year) year.textContent = new Date().getFullYear();

  /* ---------- 导航：滚动加边线 + 移动端展开 ---------- */
  var nav = document.getElementById("nav");
  var toggle = document.getElementById("navToggle");
  var links = document.getElementById("navLinks");

  if (nav) {
    var onScroll = function () {
      nav.classList.toggle("is-stuck", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "收起菜单" : "展开菜单");
    });
    // 点导航里的链接后自动收起
    if (links) {
      links.addEventListener("click", function (e) {
        if (e.target.closest("a")) {
          nav.classList.remove("is-open");
          toggle.setAttribute("aria-expanded", "false");
        }
      });
    }
  }

  /* ---------- 滚动进场 ---------- */
  var reveals = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
  if (!reveals.length) {
    // 无事可做
  } else if (reduce || !("IntersectionObserver" in window)) {
    reveals.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        var delay = parseInt(el.getAttribute("data-delay") || "0", 10);
        setTimeout(function () { el.classList.add("in"); }, delay * 90);
        io.unobserve(el);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    reveals.forEach(function (el) { io.observe(el); });
  }

  /* ---------- 通用 tab 组：aria-selected + is-active ---------- */
  function initTabs(tabSelector, panelAttr) {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(tabSelector));
    if (!tabs.length) return;

    function activate(tab) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        var panel = document.getElementById(t.getAttribute(panelAttr));
        if (panel) panel.classList.toggle("is-active", on);
      });
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { activate(tab); });
      tab.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        var next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        next.focus();
        activate(next);
      });
    });
  }

  initTabs(".tab", "aria-controls");
  initTabs(".ptab", "aria-controls");

  // 安装页：支持 #windows / #mac / #source 锚点直接定位到对应平台
  if (document.querySelector(".ptab")) {
    var hash = (location.hash || "").replace("#", "");
    var anchorMap = { windows: "pt-win", win: "pt-win", mac: "pt-mac", linux: "pt-mac", source: "pt-src" };
    var targetId = anchorMap[hash];
    if (targetId) {
      var target = document.getElementById(targetId);
      if (target) target.click();
    }
  }

  /* ---------- 图片放大 ---------- */
  var lightbox = document.getElementById("lightbox");
  var lightboxImg = document.getElementById("lightboxImg");
  var lightboxClose = document.getElementById("lightboxClose");

  if (lightbox && lightboxImg) {
    var open = function (src, alt) {
      lightboxImg.src = src;
      lightboxImg.alt = alt || "";
      lightbox.classList.add("is-open");
      document.body.style.overflow = "hidden";
      if (lightboxClose) lightboxClose.focus();
    };
    var close = function () {
      lightbox.classList.remove("is-open");
      lightboxImg.src = "";
      document.body.style.overflow = "";
    };

    document.querySelectorAll(".gallery figure[data-full]").forEach(function (fig) {
      fig.addEventListener("click", function () {
        var full = fig.getAttribute("data-full");
        var img = fig.querySelector("img");
        open(full, img ? img.alt : "");
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && lightbox.classList.contains("is-open")) close();
    });
    if (lightboxClose) lightboxClose.addEventListener("click", close);
    lightbox.addEventListener("click", function (e) {
      if (e.target === lightbox) close();
    });
  }

  /* ---------- 复制命令 ---------- */
  document.querySelectorAll(".code .copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var block = btn.parentElement;
      var text = block.textContent.replace("⧉", "").trim();
      var done = function () {
        btn.classList.add("done");
        btn.textContent = "✓";
        setTimeout(function () {
          btn.classList.remove("done");
          btn.textContent = "⧉";
        }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
      function fallback() {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); done(); } catch (err) { /* 忽略 */ }
        document.body.removeChild(ta);
      }
    });
  });
})();
