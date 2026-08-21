/** Expo push notification registration (FASE 26, ADR-0023) — the mobile
 * counterpart to `web/src/push.ts`'s Web Push flow. Expo push needs no
 * VAPID-equivalent client setup: just permission + a device token, handed
 * to the backend which sends via Expo's push API server-side.
 */

import * as Device from 'expo-device'
import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'
import { api } from './api'

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
})

export function isPushSupported(): boolean {
  // Push tokens require a physical device — the simulator/emulator has no
  // registration with Apple/Google's push services.
  return Device.isDevice
}

/** Requests permission, registers the device with Expo, and hands the
 * resulting token to the backend. Throws with a user-facing message on any
 * failure — same contract as the web version. */
export async function subscribeToExpoPush(): Promise<void> {
  if (!Device.isDevice) {
    throw new Error('Notificações push exigem um dispositivo físico (não funciona no emulador)')
  }

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'default',
      importance: Notifications.AndroidImportance.DEFAULT,
    })
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync()
  let finalStatus = existingStatus
  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync()
    finalStatus = status
  }
  if (finalStatus !== 'granted') {
    throw new Error('Permissão de notificação negada')
  }

  const { data: expoPushToken } = await Notifications.getExpoPushTokenAsync()
  await api.registerExpoPushToken(expoPushToken)
}
