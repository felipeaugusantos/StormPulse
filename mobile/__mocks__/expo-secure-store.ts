/** In-memory fake for `expo-secure-store` — the real module talks to the
 * platform Keystore/Keychain, unavailable under Jest. Same async
 * signatures as the real API. */

const store = new Map<string, string>()

export async function getItemAsync(key: string): Promise<string | null> {
  return store.has(key) ? store.get(key)! : null
}

export async function setItemAsync(key: string, value: string): Promise<void> {
  store.set(key, value)
}

export async function deleteItemAsync(key: string): Promise<void> {
  store.delete(key)
}

/** Test-only helper — not part of the real expo-secure-store API. */
export function __reset(): void {
  store.clear()
}
