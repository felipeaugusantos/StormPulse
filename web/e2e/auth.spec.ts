import { expect, test } from '@playwright/test'

/** Fase 1 (Segurança e Qualidade) — cobre, ponta-a-ponta contra um backend
 * real (nenhum mock de API própria), os dois fluxos mais críticos da
 * aplicação: cadastro e login. Precisa de uma API real rodando em
 * VITE_API_URL (ver e2e/README.md). */

const PASSWORD = 'supersecret123'

function uniqueEmail(): string {
  return `e2e-auth-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
}

test('cadastro cria a conta e entra; sair e logar de novo com a mesma senha funciona', async ({
  page,
}) => {
  const email = uniqueEmail()

  await page.goto('/')
  await page.getByRole('button', { name: 'Criar conta grátis' }).click()
  await page.getByRole('button', { name: 'Criar conta' }).click()

  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(PASSWORD)
  await page.getByLabel('Confirmar senha').fill(PASSWORD)
  await page.getByLabel(/Li e aceito os/).check()
  await page.getByRole('button', { name: 'Criar conta' }).click()

  await expect(page.getByText('📍 Locais monitorados')).toBeVisible()

  await page.getByRole('button', { name: 'Sair' }).click()
  await expect(page.getByRole('button', { name: 'Entrar' })).toBeVisible()

  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Entrar' }).click()

  await expect(page.getByText('📍 Locais monitorados')).toBeVisible()
})

test('login com senha errada mostra um erro e não entra', async ({ page }) => {
  const email = uniqueEmail()

  // Precisa de uma conta existente — cria uma só pra este teste.
  await page.goto('/')
  await page.getByRole('button', { name: 'Criar conta grátis' }).click()
  await page.getByRole('button', { name: 'Criar conta' }).click()
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(PASSWORD)
  await page.getByLabel('Confirmar senha').fill(PASSWORD)
  await page.getByLabel(/Li e aceito os/).check()
  await page.getByRole('button', { name: 'Criar conta' }).click()
  await expect(page.getByText('📍 Locais monitorados')).toBeVisible()
  await page.getByRole('button', { name: 'Sair' }).click()

  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha', { exact: true }).fill('senha-errada-123')
  await page.getByRole('button', { name: 'Entrar' }).click()

  await expect(page.locator('p.error')).toBeVisible()
  await expect(page.getByText('📍 Locais monitorados')).not.toBeVisible()
})
