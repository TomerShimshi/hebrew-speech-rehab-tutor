// Service worker (sub-plan 11): shows the daily reminder notification and opens the app when
// it's tapped. It caches nothing -- the app always loads fresh from the server.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data?.text() };
  }
  event.waitUntil(self.registration.showNotification(data.title || "דברו איתי", {
    body: data.body || "",
    icon: "icon-192.png",
    badge: "icon-192.png",
    dir: "rtl",
    lang: "he",
    tag: "daily-reminder", // a new reminder replaces an unread one instead of piling up
    data: { url: data.url || "./" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "./", self.registration.scope).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (client.url.startsWith(self.registration.scope) && "focus" in client) return client.focus();
    }
    return self.clients.openWindow(url);
  })());
});
