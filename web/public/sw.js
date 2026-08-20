// StormPulse service worker — Web Push only (FASE 22). No offline caching,
// no asset interception: this exists purely to receive `push` events while
// the app isn't in the foreground and turn them into an OS notification.

self.addEventListener('push', (event) => {
  let payload = { title: 'StormPulse', body: 'Novo alerta.' }
  try {
    if (event.data) payload = event.data.json()
  } catch {
    // Non-JSON payload — fall back to the generic message above.
  }

  event.waitUntil(
    self.registration.showNotification(payload.title || 'StormPulse', {
      body: payload.body,
      data: { url: '/' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = event.notification.data?.url || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) return client.focus()
      }
      return self.clients.openWindow(targetUrl)
    }),
  )
})
