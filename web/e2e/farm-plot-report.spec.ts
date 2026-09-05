import { expect, test } from '@playwright/test'

/** Fase 1 (Segurança e Qualidade) — cobre, ponta-a-ponta contra um backend
 * real, cadastro de fazenda, cadastro de talhão e geração de relatório
 * semanal. Escopo deliberadamente não inclui desenhar o contorno no mapa
 * (canvas WebGL — cobertura de contorno já existe em
 * backend/tests/test_integration_locations.py); o talhão aqui é criado sem
 * `boundary_geojson`, que é opcional na criação.
 *
 * A busca de cidade chama a Nominatim (OpenStreetMap) diretamente do
 * navegador — interceptada aqui pra não depender de um serviço de
 * terceiros nem do limite de 1 req/s dela em CI. */

const PASSWORD = 'supersecret123'

function uniqueSuffix(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1e6)}`
}

test('cadastra fazenda, cadastra talhão e abre o relatório semanal gerado', async ({ page }) => {
  const suffix = uniqueSuffix()
  const email = `e2e-farm-${suffix}@example.com`
  const farmLabel = `Fazenda E2E ${suffix}, Ribeirão Preto, SP, Brasil`
  const plotName = `Talhão E2E ${suffix}`

  await page.route('https://nominatim.openstreetmap.org/search**', (route) =>
    route.fulfill({
      json: [{ display_name: farmLabel, lat: '-21.1775', lon: '-47.8103' }],
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'Criar conta grátis' }).click()
  await page.getByRole('button', { name: 'Criar conta' }).click()

  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(PASSWORD)
  await page.getByLabel('Confirmar senha').fill(PASSWORD)
  await page.getByLabel('🌾 Agro').check()
  await page.getByLabel(/Li e aceito os/).check()
  await page.getByRole('button', { name: 'Criar conta' }).click()

  await expect(page.getByText('📍 Locais monitorados')).toBeVisible()

  // Cadastro de fazenda — busca a cidade (mockada acima), escolhe o
  // resultado e confirma o formulário de criação.
  await page.getByPlaceholder('Buscar cidade (ex: Ribeirão Preto)').fill('Ribeirão Preto')
  await page.getByText(farmLabel).click()
  await page.getByRole('button', { name: 'Adicionar' }).click()
  await expect(page.getByText(farmLabel.split(',')[0]).first()).toBeVisible()

  // Talhão só existe na aba Agro (o botão tem `role="tab"` explícito).
  await page.getByRole('tab', { name: '🌾 Agro' }).click()
  await page.getByRole('button', { name: '+ talhão' }).click()

  await page.locator('label:text-is("Nome do talhão") + input').fill(plotName)
  await page.getByPlaceholder('soja, milho, café…').first().fill('soja')
  await page.getByRole('button', { name: 'Adicionar talhão' }).click()

  await expect(page.getByText(`🌱 ${plotName}`)).toBeVisible()

  // Geração de relatório — abre o modal e espera o relatório (não o
  // estado de carregando/erro) renderizar de fato.
  await page.getByTitle('Relatório semanal').click()
  const modal = page.locator('.modal-card', { hasText: `Relatório semanal — ${plotName}` })
  await expect(modal).toBeVisible()
  // Escopado ao modal: o dashboard por trás já tem seu próprio painel de
  // chuva acumulada da fazenda, com o mesmo texto de rótulo.
  await expect(modal.getByText('chuva acumulada', { exact: true })).toBeVisible({
    timeout: 15_000,
  })
  await expect(modal.getByText('dias secos', { exact: true })).toBeVisible()
})
