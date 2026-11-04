/* PWA 公共脚本：service worker 注册 + 安装事件捕获（主应用与安装页共用） */
(() => {
  "use strict";

  // 捕获 Chrome 的安装事件，供安装页的「立即安装」按钮触发
  window.__deferredInstallPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    window.__deferredInstallPrompt = e;
    document.dispatchEvent(new CustomEvent("m2s:installable"));
  });
  window.addEventListener("appinstalled", () => {
    document.dispatchEvent(new CustomEvent("m2s:installed"));
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* http 环境或浏览器不支持时静默降级：应用功能不受影响 */
      });
    });
  }
})();
