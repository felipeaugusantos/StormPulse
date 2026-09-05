import { defineConfig, devices } from '@playwright/test'

// Fase 1 (Segurança e Qualidade) — E2E deliberadamente pequeno (2 specs)
// cobrindo só os fluxos mais críticos ponta-a-ponta contra um backend real
// (não mockado): cadastro/login, e cadastro de fazenda+talhão+geração de
// relatório. Assume que a API já está rodando em VITE_API_URL (padrão
// http://localhost:8000, igual ao default do app) — ver e2e/README.md.
const PORT = 5173

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'dot' : 'list',
  timeout: 30_000,
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
