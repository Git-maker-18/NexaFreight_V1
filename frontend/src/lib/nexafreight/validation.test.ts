import { describe, expect, it } from 'vitest'

import {
  formatCheckValue,
  summarizeValidation,
  type ValidationMatrix,
} from './validation'

function matrix(overrides: Partial<ValidationMatrix> = {}): ValidationMatrix {
  return {
    generated_at: '2026-09-24T12:00:00Z',
    all_ok: true,
    pass_count: 3,
    total_count: 3,
    static: [
      { name: 'sea CO2 EF g/tkm', actual: 8.0, ref: 8.0, tol: 0.6, ok: true },
      { name: 'carbon price $/kg', actual: 0.08, ref: 0.08, tol: 0.02, ok: true },
    ],
    artifact: [{ name: 'p50 pinball', actual: 0.5054, ref: 0.5054, tol: 0.01, ok: true }],
    skips: [],
    ...overrides,
  }
}

describe('summarizeValidation', () => {
  it('summarizes a green matrix', () => {
    const s = summarizeValidation(matrix())
    expect(s.allOk).toBe(true)
    expect(s.passCount).toBe(3)
    expect(s.totalCount).toBe(3)
    expect(s.failed).toHaveLength(0)
  })

  it('fails loudly and hoists failures to the top', () => {
    const bad = matrix({
      all_ok: false,
      pass_count: 2,
      static: [
        { name: 'sea CO2 EF g/tkm', actual: 6.5, ref: 8.0, tol: 0.6, ok: false },
        { name: 'carbon price $/kg', actual: 0.08, ref: 0.08, tol: 0.02, ok: true },
      ],
    })
    const s = summarizeValidation(bad)
    expect(s.allOk).toBe(false)
    expect(s.failed.map((f) => f.name)).toEqual(['sea CO2 EF g/tkm'])
    expect(s.ordered[0].name).toBe('sea CO2 EF g/tkm')
  })

  it('carries skips through', () => {
    const s = summarizeValidation(matrix({ skips: ['ETA artifact metadata not found'] }))
    expect(s.skips).toEqual(['ETA artifact metadata not found'])
  })
})

describe('formatCheckValue', () => {
  it('keeps integers clean and trims float noise', () => {
    expect(formatCheckValue(88)).toBe('88')
    expect(formatCheckValue(3.1679999999999997)).toBe('3.168')
    expect(formatCheckValue(0.5054)).toBe('0.5054')
  })
})
