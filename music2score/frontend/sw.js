/* music2score service worker
 * 缓存应用外壳，让手机添加到主屏幕后断网也能打开界面。
 * 转谱计算必须连服务端，/api/ 一律走网络并给出明确的离线提示。
 */
const CACHE = 'm2score-v2';
const SHELL = [
  '/', '/index.html', '/install',
  '/styles/fonts.css', '/styles/tokens.css', '/styles/base.css',
  '/styles/components.css', '/styles/install.css',
  '/scripts/main.js', '/scripts/install.js', '/scripts/pwa.js',
  '/manifest.webmanifest', '/downloads.json',
  '/icons/icon.svg', '/icons/icon-192.png', '/icons/icon-512.png',
  '/icons/apple-touch-icon.png', '/icons/maskable-512.png'
  // 字体 woff2 约 230 KB，首次访问时按 cache-first 落盘，不占安装体积
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
      .catch((err) => console.warn('[sw] 预缓存部分资源失败', err))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 接口不缓存；离线时返回可读的中文错误，前端能直接展示
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => new Response(
        JSON.stringify({ error: '当前离线，转谱需要连接服务端' }),
        { status: 503, headers: { 'Content-Type': 'application/json; charset=utf-8' } }
      ))
    );
    return;
  }

  // 静态资源：cache-first + 后台静默更新
  event.respondWith(
    caches.match(req).then((hit) => {
      const network = fetch(req).then((res) => {
        if (res && res.ok && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => hit);
      return hit || network;
    })
  );
});
