/** Secure, encrypted-at-rest storage for the access/refresh token pair
 * (hardening Fase 3) — `expo-secure-store` uses the platform Keystore
 * (Android) / Keychain (iOS), unlike `AsyncStorage`, which is plain,
 * unencrypted disk storage. Tokens never touch `AsyncStorage` or any log
 * line in this module. */

import * as SecureStore from 'expo-secure-store'

const ACCESS_TOKEN_KEY = 'stormpulse.access_token'
const REFRESH_TOKEN_KEY = 'stormpulse.refresh_token'

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(ACCESS_TOKEN_KEY)
}

export async function setAccessToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, token)
}

export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_TOKEN_KEY)
}

export async function setRefreshToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token)
}

export async function setTokenPair(accessToken: string, refreshToken: string): Promise<void> {
  await Promise.all([setAccessToken(accessToken), setRefreshToken(refreshToken)])
}

/** Full logout — both tokens removed. Never throws: a failed delete (e.g.
 * key never existed) must not block the user from reaching the login
 * screen. */
export async function clearTokens(): Promise<void> {
  await Promise.allSettled([
    SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
    SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
  ])
}

/** Whether there's a refresh token to resume a session with — the real
 * "am I logged in?" signal, not the (short-lived, 15min) access token,
 * which may have already expired while the app was closed. */
export async function hasSession(): Promise<boolean> {
  return (await getRefreshToken()) != null
}
