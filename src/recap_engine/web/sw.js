self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("fetch", () => {});  // online-only (local server); enables PWA install
