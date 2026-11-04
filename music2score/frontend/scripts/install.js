/* 安装页逻辑：地址 / 二维码 / 平台检测 / 原生包配置 / 安装触发 */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);

  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent)
      || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /android/i.test(navigator.userAgent);

  let lanUrl = "";

  /* ---------- 平台检测 ---------- */
  function markPlatform() {
    const hint = $("#heroHint");
    if (isAndroid) {
      hint.textContent = "已检测到 Android 设备 · 下面的安卓卡片为你标了出来";
      $("#card-android").classList.add("recommended");
      $("#badge-android").hidden = false;
    } else if (isIOS) {
      hint.textContent = "已检测到 iPhone / iPad · 请用 Safari 打开本页";
      $("#card-ios").classList.add("recommended");
      $("#badge-ios").hidden = false;
    } else {
      hint.textContent = "当前是电脑浏览器 · 手机端请扫码或输入下方地址";
    }
  }

  /* ---------- 局域网地址与二维码 ---------- */
  async function loadInfo() {
    try {
      const res = await fetch("/api/install-info");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const info = await res.json();
      lanUrl = info.lan_url || "";
      $("#lanUrl").textContent = lanUrl;
      $("#qrImg").src = `/api/qr?text=${encodeURIComponent(lanUrl)}&size=8`;
      applyDownloads(info.downloads || {});
    } catch (e) {
      $("#lanUrl").textContent = "获取失败：请确认服务端正在运行";
      $("#copyBtn").disabled = true;
    }
  }

  function applyDownloads(d) {
    const androidNative = d.android && d.android.available && d.android.apk_url;
    const iosNative = d.ios && d.ios.available && (d.ios.appstore_url || d.ios.testflight_url);

    if (androidNative) {
      const box = $("#dl-android-native");
      box.hidden = false;
      box.querySelector("a").href = d.android.apk_url;
      box.querySelector(".native-meta").textContent =
        [d.android.version && `v${d.android.version}`, d.android.size]
          .filter(Boolean).join(" · ") || "APK 直装";
    }
    if (iosNative) {
      const box = $("#dl-ios-native");
      box.hidden = false;
      box.querySelector("a").href = d.ios.appstore_url || d.ios.testflight_url;
      box.querySelector(".native-meta").textContent =
        [d.ios.version && `v${d.ios.version}`, d.ios.appstore_url ? "App Store" : "TestFlight"]
          .filter(Boolean).join(" · ") || "";
    }
    $("#nativeStatus").textContent =
      androidNative || iosNative ? "✓ 已发布原生包" : "未发布（downloads.json 可配置）";
  }

  /* ---------- 复制 ---------- */
  async function copyUrl() {
    if (!lanUrl) return;
    const btn = $("#copyBtn");
    try {
      await navigator.clipboard.writeText(lanUrl);
    } catch (_) {
      // 兼容非安全上下文（http 局域网地址）
      const ta = document.createElement("textarea");
      ta.value = lanUrl;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    const old = btn.textContent;
    btn.textContent = "已复制";
    btn.disabled = true;
    setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1600);
  }

  /* ---------- 平台按钮 ---------- */
  function bindButtons() {
    $("#copyBtn").addEventListener("click", copyUrl);

    // 安卓：Chrome 的安装弹窗可用时直接触发
    const btnA = $("#btnAndroidInstall");
    const enableA = () => {
      btnA.disabled = false;
      btnA.textContent = "立即安装";
    };
    if (window.__deferredInstallPrompt) enableA();
    document.addEventListener("m2s:installable", enableA);
    document.addEventListener("m2s:installed", () => {
      btnA.textContent = "✓ 已安装到主屏幕";
      btnA.disabled = true;
    });
    btnA.addEventListener("click", async () => {
      const prompt = window.__deferredInstallPrompt;
      if (!prompt) return;
      prompt.prompt();
      try {
        await prompt.userChoice;
      } catch (_) { /* 用户取消 */ }
    });

    // iOS：跳到手机版地址；桌面端点了就滚到步骤区
    $("#btnIosOpen").addEventListener("click", () => {
      if (isIOS) {
        window.location.href = "/";
      } else {
        $("#card-ios").scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }

  markPlatform();
  bindButtons();
  loadInfo();
})();
