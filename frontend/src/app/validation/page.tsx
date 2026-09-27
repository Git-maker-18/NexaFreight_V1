'use client'

import { useEffect, useState } from 'react'
import { getValidationMatrix, type ValidationMatrixResponse } from '@/lib/nexafreight/client'
import { formatCheckValue, summarizeValidation } from '@/lib/nexafreight/validation'

/**
 * Task 17: public validation page — renders the LIVE reference-validation
 * matrix served by /api/health/validation (same implementation as the CI
 * gate). "No uncalibrated number on screen", visible to everyone.
 */
export default function ValidationPage() {
  const [matrix, setMatrix] = useState<ValidationMatrixResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getValidationMatrix()
      .then((m) => {
        if (!cancelled) setMatrix(m)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const summary = matrix ? summarizeValidation(matrix) : null

  return (
    <main style={{ maxWidth: 880, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>Validation Matrix</h1>
      <p style={{ color: '#666', fontSize: 13, marginBottom: 16 }}>
        Every model constant checked against published external references — the same
        checks that gate CI (eval/validate.py). {matrix ? `Generated ${new Date(matrix.generated_at).toLocaleString()}` : ''}
      </p>

      {error && (
        <div role="alert" style={{ padding: 12, border: '1px solid #b91c1c', borderRadius: 8, color: '#b91c1c' }}>
          Failed to load the validation matrix: {error}
        </div>
      )}

      {!matrix && !error && <p style={{ color: '#666' }}>Loading…</p>}

      {summary && (
        <>
          <div
            data-testid="validation-banner"
            style={{
              padding: '10px 14px',
              borderRadius: 8,
              marginBottom: 14,
              border: `1px solid ${summary.allOk ? '#15803d' : '#b91c1c'}`,
              color: summary.allOk ? '#15803d' : '#b91c1c',
              fontWeight: 600,
              background: summary.allOk ? '#f0fdf4' : '#fef2f2',
            }}
          >
            {summary.allOk ? 'GREEN' : 'RED'} — {summary.passCount}/{summary.totalCount} checks pass
          </div>

          {summary.skips.length > 0 && (
            <ul style={{ color: '#92400e', fontSize: 12, marginBottom: 12 }}>
              {summary.skips.map((s) => (
                <li key={s}>SKIP: {s}</li>
              ))}
            </ul>
          )}

          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
                <th style={{ padding: 6 }}>Check</th>
                <th style={{ padding: 6 }}>Actual</th>
                <th style={{ padding: 6 }}>Reference</th>
                <th style={{ padding: 6 }}>Tolerance</th>
              </tr>
            </thead>
            <tbody>
              {summary.ordered.map((row) => (
                <tr key={row.name} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={{ padding: 6, color: row.ok ? undefined : '#b91c1c', fontWeight: row.ok ? 400 : 600 }}>
                    {row.ok ? '✅' : '❌'} {row.name}
                    {row.one_sided ? ' (one-sided)' : ''}
                  </td>
                  <td style={{ padding: 6 }}>{formatCheckValue(row.actual)}</td>
                  <td style={{ padding: 6 }}>{formatCheckValue(row.ref)}</td>
                  <td style={{ padding: 6 }}>±{formatCheckValue(row.tol)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  )
}
