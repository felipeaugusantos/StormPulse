import { generateId } from '../fieldnotes/id'

describe('generateId (Fase 6, ADR-0090)', () => {
  test('produces a well-formed v4 UUID', () => {
    const id = generateId()
    expect(id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    )
  })

  test('is not the same value twice in a row', () => {
    expect(generateId()).not.toBe(generateId())
  })
})
