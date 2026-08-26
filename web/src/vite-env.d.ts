/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  readonly VITE_GOOGLE_CLIENT_ID?: string
  readonly VITE_VAPID_PUBLIC_KEY?: string
  readonly VITE_HCAPTCHA_SITE_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

// Minimal ambient typing for the Google Identity Services script, loaded
// dynamically at runtime (not an npm dependency — see components/Login.tsx).
interface GoogleCredentialResponse {
  credential: string
}

interface Window {
  google?: {
    accounts: {
      id: {
        initialize(config: {
          client_id: string
          callback: (response: GoogleCredentialResponse) => void
        }): void
        renderButton(parent: HTMLElement, options: Record<string, unknown>): void
      }
    }
  }
  // Minimal ambient typing for the hCaptcha script, loaded dynamically at
  // runtime (not an npm dependency — see components/Login.tsx), same
  // pattern as `google` above.
  hcaptcha?: {
    render(
      container: HTMLElement,
      options: { sitekey: string; callback: (token: string) => void },
    ): string
    reset(widgetId?: string): void
  }
}
