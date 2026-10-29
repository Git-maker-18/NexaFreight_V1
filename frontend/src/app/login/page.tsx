'use client'

import LoadingGlobe from '@/components/art/LoadingGlobe';

import { useState, useRef, useEffect, type FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Eye, EyeOff, ShieldCheck } from 'lucide-react'
import { login } from '@/lib/nexafreight/client'
import { NexaHttpError, NexaNetworkError } from '@/lib/nexafreight/errors'
import { useAuthStore } from '@/store/useAuthStore'
import { getCurrentUser } from '@/lib/nexafreight/client'

// ─── Inner form (needs access to auth store context) ─────────────────────────

function LoginForm() {
  const router = useRouter()
  const { setAuth } = useAuthStore()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [expiredNotice, setExpiredNotice] = useState(false)
  const emailRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const p = new URLSearchParams(window.location.search)
      if (p.get('reason') === 'expired') {
        setExpiredNotice(true)
      }
    }
    emailRef.current?.focus()
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      // login() auto-stores the token in client.ts's module-level store
      const loginResp = await login(email.trim(), password)

      // Fetch the full user profile (UserOut shape, has id)
      const user = await getCurrentUser()

      // Persist into React context so components can read it
      setAuth(loginResp.access_token, user)

      // Redirect to the main NexaFreight dashboard
      router.push('/')
    } catch (err) {
      console.error('[NexaFreight login error]', err)
      if (err instanceof NexaHttpError && err.status === 429) {
        setError('Too many failed attempts. Rate limit reached — please wait 60s.')
      } else if (err instanceof NexaHttpError && err.isUnauthorized) {
        setError('Invalid credentials. Check your email and password.')
      } else if (err instanceof NexaNetworkError) {
        const detail = err.cause instanceof Error ? err.cause.message : String(err.cause ?? '')
        setError(`Cannot reach backend server (${detail || 'offline'}). Check network or cold-start banner.`)
      } else if (err instanceof NexaHttpError) {
        setError(`Server error ${err.status}: ${err.detail}`)
      } else {
        setError('Unexpected error. Check the browser console for details.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.page}>
      <div className="hidden lg:block" aria-hidden="true" style={{ flexShrink: 0 }}>
        <LoadingGlobe size={400} caption="OPERATOR ACCESS" progress="SECURE CHANNEL READY" />
      </div>
      <motion.main
        className="login-card"
        style={styles.card}
        initial={{ opacity: 0, y: 24, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        role="main"
        aria-label="NexaFreight login"
      >
        {/* Header */}
        <div style={styles.header}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/nexafreight-logo-horizontal.svg"
            alt="NexaFreight — Control Tower"
            style={{ width: '100%', maxWidth: 300, height: 'auto', marginBottom: 12, display: 'block', margin: '0 auto 12px auto' }}
          />
          <div style={styles.divider} />
        </div>

        {expiredNotice && (
          <div
            style={{
              padding: '10px 12px',
              marginBottom: 16,
              background: 'transparent',
              border: `1px solid var(--alert-orange)`,
              borderRadius: 2,
              color: 'var(--alert-orange)',
              fontSize: 12,
              fontFamily: 'var(--font-ui)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <span>⚠</span>
            <span>Authentication token expired. Click Authenticate below to reconnect.</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} noValidate style={styles.form}>
          <div style={styles.fieldGroup}>
            <label htmlFor="nf-email" style={styles.label}>
              EMAIL
            </label>
            <input
              id="nf-email"
              ref={emailRef}
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="operator@nexafreight.local"
              style={styles.input}
              disabled={loading}
              aria-describedby={error ? 'nf-error' : undefined}
            />
          </div>

          <div style={styles.fieldGroup}>
            <label htmlFor="nf-password" style={styles.label}>
              PASSWORD
            </label>
            <div style={{ position: 'relative', width: '100%', display: 'flex', alignItems: 'center' }}>
              <input
                id="nf-password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Enter your password"
                style={{ ...styles.input, paddingRight: 40 }}
                disabled={loading}
              />
              <button
                type="button"
                onClick={() => setShowPassword(prev => !prev)}
                style={styles.eyeButton}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                title={showPassword ? 'Hide password' : 'Show password'}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={16} strokeWidth={1.8} /> : <Eye size={16} strokeWidth={1.8} />}
              </button>
            </div>
          </div>

          {/* Error message */}
          <AnimatePresence mode="wait">
            {error && (
              <motion.div
                id="nf-error"
                role="alert"
                aria-live="assertive"
                style={styles.errorBox}
                initial={{ opacity: 0, height: 0, marginTop: 0 }}
                animate={{ opacity: 1, height: 'auto', marginTop: 4 }}
                exit={{ opacity: 0, height: 0, marginTop: 0 }}
                transition={{ duration: 0.22 }}
              >
                <span style={styles.errorIcon} aria-hidden="true">⚠</span>
                {error}
              </motion.div>
            )}
          </AnimatePresence>

          <motion.button
            id="nf-submit"
            type="submit"
            disabled={loading || !email || !password}
            style={{
              ...styles.button,
              opacity: loading || !email || !password ? 0.6 : 1,
              cursor: loading || !email || !password ? 'not-allowed' : 'pointer',
            }}
            whileHover={loading ? {} : { scale: 1.02 }}
            whileTap={loading ? {} : { scale: 0.98 }}
          >
            {loading ? (
              <span style={styles.buttonLoading}>
                <motion.span
                  animate={{ rotate: 360 }}
                  transition={{ duration: 0.9, repeat: Infinity, ease: 'linear' }}
                  style={{ display: 'inline-block' }}
                >
                  ◈
                </motion.span>
                &nbsp;AUTHENTICATING…
              </span>
            ) : (
              'AUTHENTICATE'
            )}
          </motion.button>
        </form>

        {/* Default credentials card */}
        <div style={styles.demoCard}>
          <div style={styles.demoHeader}>
            <ShieldCheck size={14} style={{ color: 'var(--cobalt)' }} />
            <span>OPERATIONAL ACCESS CREDENTIALS</span>
          </div>
          <div style={styles.demoRow}>
            <span style={styles.demoLabel}>Account:</span>
            <code style={styles.code}>operator@nexafreight.local</code>
          </div>
          <div style={styles.demoRow}>
            <span style={styles.demoLabel}>Password:</span>
            <code style={styles.code}>password123</code>
          </div>
          <button
            type="button"
            style={styles.fillButton}
            onClick={() => {
              setEmail('operator@nexafreight.local')
              setPassword('password123')
              setError(null)
            }}
          >
            AUTO-FILL OPERATOR CREDENTIALS
          </button>
        </div>
      </motion.main>
    </div>
  )
}

export default function LoginPage() {
  return <LoginForm />
}

// ─── Styles (inline, using Chartroom CSS variables) ──────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 40,
    background: 'transparent',
    fontFamily: 'var(--font-ui)',
    position: 'relative',
    overflow: 'hidden',
  },

  // Flat waybill-style card with corner registration ticks (via CSS)
  card: {
    position: 'relative',
    zIndex: 10,
    width: '100%',
    maxWidth: 420,
    margin: '0 16px',
    padding: '36px 32px 28px',
    background: 'var(--paper)',
    border: '1px solid var(--border-hairline)',
    borderRadius: 3,
    boxShadow: 'none',
    backdropFilter: 'none',
  },

  // Header section
  header: {
    textAlign: 'center',
    marginBottom: 24,
  },

  divider: {
    height: 1,
    background: 'var(--border-hairline)',
    margin: '16px 0',
  },

  // Form
  form: {
    marginTop: 16,
  },

  fieldGroup: {
    marginBottom: 16,
  },

  label: {
    display: 'block',
    fontSize: '11px',
    fontWeight: 600,
    letterSpacing: '0.06em',
    color: 'var(--ink)',
    fontFamily: 'var(--font-ui)',
    marginBottom: 6,
    textTransform: 'uppercase',
  },

  input: {
    width: '100%',
    padding: '8px 12px',
    fontFamily: 'var(--font-ui)',
    fontSize: '13px',
    fontWeight: 400,
    color: 'var(--ink)',
    background: 'var(--paper)',
    border: '1px solid var(--border-hairline)',
    borderRadius: 2,
    boxSizing: 'border-box',
    outline: 'none',
  },

  eyeButton: {
    position: 'absolute',
    right: 10,
    top: '50%',
    transform: 'translateY(-50%)',
    background: 'none',
    border: 'none',
    padding: 4,
    cursor: 'pointer',
    color: 'var(--text-secondary, #71717a)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },

  // Error box
  errorBox: {
    display: 'flex',
    alignItems: 'flex-start',
    padding: '10px 12px',
    background: 'transparent',
    border: '1px solid var(--oxide-risk)',
    borderRadius: 2,
    color: 'var(--oxide-risk)',
    fontSize: '12px',
    fontFamily: 'var(--font-ui)',
    lineHeight: 1.5,
    gap: 8,
  },

  errorIcon: {
    flexShrink: 0,
    marginTop: 1,
  },

  // Submit button
  button: {
    width: '100%',
    padding: '10px 16px',
    fontFamily: 'var(--font-ui)',
    fontSize: '13px',
    fontWeight: 600,
    letterSpacing: '0.05em',
    color: 'var(--paper)',
    background: 'var(--cobalt)',
    border: 'none',
    borderRadius: 2,
    cursor: 'pointer',
    textTransform: 'uppercase',
    boxSizing: 'border-box',
  },

  buttonLoading: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },

  // Demo card
  demoCard: {
    marginTop: 22,
    padding: '12px 14px',
    background: 'rgba(0, 0, 0, 0.02)',
    border: '1px dashed var(--border-hairline, #d4d4d8)',
    borderRadius: 3,
    fontSize: '11px',
    fontFamily: 'var(--font-ui)',
  },

  demoHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontWeight: 600,
    fontSize: '10px',
    letterSpacing: '0.05em',
    color: 'var(--ink, #18181b)',
    marginBottom: 8,
    textTransform: 'uppercase',
  },

  demoRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginBottom: 4,
  },

  demoLabel: {
    color: 'var(--text-secondary, #71717a)',
    fontSize: '11px',
    width: 60,
  },

  code: {
    fontFamily: 'var(--font-mono, monospace)',
    fontSize: '11px',
    color: 'var(--cobalt, #2547C8)',
  },

  fillButton: {
    marginTop: 8,
    width: '100%',
    padding: '6px 10px',
    background: 'var(--paper, #ffffff)',
    border: '1px solid var(--border-hairline, #d4d4d8)',
    borderRadius: 2,
    color: 'var(--cobalt, #2547C8)',
    fontSize: '10px',
    fontWeight: 600,
    fontFamily: 'var(--font-mono, monospace)',
    letterSpacing: '0.05em',
    cursor: 'pointer',
    textTransform: 'uppercase',
  },
}
