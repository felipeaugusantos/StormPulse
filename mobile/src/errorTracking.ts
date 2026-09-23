import * as Sentry from '@sentry/react-native'

/** No-op without `EXPO_PUBLIC_SENTRY_DSN` configured — mesmo padrão de
 * "opt-in honesto" já usado pelo `EXPO_PUBLIC_API_URL` (config.ts) e
 * pela versão web deste mesmo módulo (web/src/errorTracking.ts). Um DSN
 * do Sentry não é segredo de controle de acesso (só permite *enviar*
 * eventos), então fica exposto no bundle como qualquer `EXPO_PUBLIC_*`. */
export function initErrorTracking(): void {
  const dsn = process.env.EXPO_PUBLIC_SENTRY_DSN
  if (!dsn) return
  Sentry.init({
    dsn,
    // Error events only — mesmo escopo da versão web, sem trace sampling.
    tracesSampleRate: 0,
  })
}
