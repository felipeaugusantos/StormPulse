/** Web Push opt-in (FASE 22) — browser-native, no FCM/APNs account needed.
 *
 * `PushManager.subscribe()` requires the VAPID public key as a raw
 * Uint8Array, not the base64url string it's transported/stored as —
 * `urlBase64ToUint8Array` does that conversion.
 */

import { api } from './api'

export function isPushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window
}

function urlBase64ToUint8Array(base64: string): BufferSource {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const normalized = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(normalized)
  const bytes = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return bytes
}

/** Registers the service worker (idempotent — browsers no-op a repeat
 * `register()` for the same script URL), requests notification permission,
 * subscribes, and sends the subscription to the backend. Throws with a
 * user-facing message on any failure — callers show it, they don't retry
 * silently (a push permission prompt is a one-shot user gesture). */
export async function subscribeToPush(): Promise<void> {
  if (!isPushSupported()) {
    throw new Error('Notificações push não são suportadas neste navegador')
  }
  const vapidPublicKey = import.meta.env.VITE_VAPID_PUBLIC_KEY
  if (!vapidPublicKey) {
    throw new Error('Notificações push não estão configuradas neste ambiente')
  }

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error('Permissão de notificação negada')
  }

  const registration = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
  })

  const json = subscription.toJSON()
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    throw new Error('Assinatura de notificação incompleta')
  }

  await api.registerPushSubscription({
    endpoint: json.endpoint,
    keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
  })
}
