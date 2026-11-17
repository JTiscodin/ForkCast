// Forkcast service worker: shows meal-time reminders pushed by the backend, even with no tab open.
self.addEventListener("push", (e) => {
  const d = e.data ? e.data.json() : {};
  e.waitUntil(
    self.registration.showNotification(d.title || "Forkcast", {
      body: d.body,
      tag: d.tag,
      icon: "/brand/forkcast.png",
      data: { url: d.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || "/", self.location.origin).href;
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
      const tab = tabs.find((t) => new URL(t.url).origin === self.location.origin);
      return tab ? tab.focus().then((t) => t.navigate(url)) : self.clients.openWindow(url);
    })
  );
});
