/**
 * Validation-matrix helpers (Task 17). Pure logic lives here so it can be
 * unit-tested without the network; the fetch call lives in client.ts.
 */

export interface ValidationCheck {
  name: string
  actual: number
  ref: number
  tol: number
  ok: boolean
  one_sided?: boolean | null
}

export interface ValidationMatrix {
  generated_at: string
  all_ok: boolean
  pass_count: number
  total_count: number
  static: ValidationCheck[]
  artifact: ValidationCheck[]
  skips: string[]
}

export interface ValidationSummary {
  allOk: boolean
  passCount: number
  totalCount: number
  failed: ValidationCheck[]
  skips: string[]
  /** newest first: failed rows, then the rest in original order */
  ordered: ValidationCheck[]
}

export function summarizeValidation(matrix: ValidationMatrix): ValidationSummary {
  const all = [...matrix.static, ...matrix.artifact]
  const failed = all.filter((row) => !row.ok)
  return {
    allOk: matrix.all_ok,
    passCount: matrix.pass_count,
    totalCount: matrix.total_count,
    failed,
    skips: matrix.skips ?? [],
    ordered: [...failed, ...all.filter((row) => row.ok)],
  }
}

export function formatCheckValue(value: number): string {
  if (Number.isInteger(value)) return String(value)
  return String(Math.round(value * 1e4) / 1e4)
}
