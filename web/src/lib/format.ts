const eurFmt = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 })
const eurFmt0 = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const numFmt = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 })

export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

export function eur(v: unknown, whole = false): string {
  if (!isNum(v)) return '—'
  return (whole ? eurFmt0 : eurFmt).format(v)
}

export function num(v: unknown): string {
  return isNum(v) ? numFmt.format(v) : '—'
}

export function pct(v: unknown): string {
  return isNum(v) ? `${Math.round(v * 100)}%` : '—'
}

/** "2026-11-16" → "Mon 16 Nov" (date-only strings are parsed as local dates). */
export function day(v: unknown): string {
  if (typeof v !== 'string' || !v) return '—'
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v)
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(v)
  if (Number.isNaN(d.getTime())) return v
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

/** ISO timestamp → "00:50:16" (as written by the gate, Helsinki time). */
export function clock(v: unknown): string {
  if (typeof v !== 'string') return ''
  const m = /T(\d{2}:\d{2}:\d{2})/.exec(v)
  return m ? m[1] : v
}

/** ISO timestamp → "Sat 14 Nov, 02:50". */
export function dayTime(v: unknown): string {
  if (typeof v !== 'string' || !v) return '—'
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(v)
  return m ? `${day(m[1])}, ${m[2]}` : v
}

export function ago(v: unknown): string {
  if (typeof v !== 'string') return ''
  const t = new Date(v).getTime()
  if (Number.isNaN(t)) return ''
  const s = Math.round((Date.now() - t) / 1000)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return day(v.slice(0, 10))
}

export const short = (h: unknown, n = 10) => (typeof h === 'string' ? h.slice(0, n) : '')

/** "human:Laura Mäkinen (F&B Manager)" → kind + display name. */
export function actorKind(actor: string | null | undefined): { kind: 'human' | 'gate' | 'agent'; name: string } {
  const a = actor || ''
  if (a.startsWith('human:')) return { kind: 'human', name: a.slice(6) }
  if (a.startsWith('policy:')) return { kind: 'gate', name: 'Guardrails' }
  if (a === 'valio-aimo-trade-gate' || a.includes('trade-gate')) return { kind: 'gate', name: 'Trade Gate' }
  return { kind: 'agent', name: a || 'agent' }
}

/** Try hard to parse JSON that may have been cut off at N characters. Returns null on failure. */
export function parseLoose(text: unknown): Record<string, unknown> | null {
  if (typeof text !== 'string') return null
  try {
    const v = JSON.parse(text)
    return v && typeof v === 'object' ? (v as Record<string, unknown>) : null
  } catch {
    return null
  }
}

/** Collect product id → name pairs from (possibly truncated) JSON text. */
export function harvestNames(text: unknown, into: Map<string, string>) {
  if (typeof text !== 'string') return
  const re = /"(?:id|product_id)"\s*:\s*"([^"]+)"\s*,\s*"(?:name|title)"\s*:\s*"((?:[^"\\]|\\.)*)"/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (!into.has(m[1])) {
      try {
        into.set(m[1], JSON.parse(`"${m[2]}"`))
      } catch {
        into.set(m[1], m[2])
      }
    }
  }
}
