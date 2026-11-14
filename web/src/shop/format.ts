import type { Approval } from '../types'
import { fNum, fUnit, getLang, t } from './i18n'
import type { Customer, Option } from './types'

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** "1 l" → {n: 1, u: "l"}; "kg" → {n: null, u: "kg"}. */
function parsePack(pack: string | undefined): { n: number | null; u: string } {
  const p = (pack || '').trim()
  const m = /^([\d.,]+)\s*(.*)$/.exec(p)
  if (!m) return { n: null, u: p }
  return { n: Number(m[1].replace(',', '.')), u: m[2].trim() }
}

/** How much the customer is buying, in their words: "7 kg", "6 kpl", "10 × 1 l" (locale numbers). */
export function qtyText(o: Option): string {
  const units = isNum(o.units) ? fNum(o.units) : '—'
  const { n, u } = parsePack(o.pack)
  const su = (o.sales_unit || '').toUpperCase()
  if (su === 'KG' && (u === 'kg' || !u)) return `${units} kg`
  if (su === 'L' && (u === 'l' || !u)) return `${units} l`
  if (n === null) return `${units} ${u && u !== 'st' ? u : fUnit('pcs')}`
  return `${units} × ${fNum(n)} ${u}`.trim()
}

/** Customer-meaningful allergens only (drops raw 2-letter codes the catalog sometimes carries). */
export function cleanAllergens(a: string[] | undefined): string[] {
  return (a || []).filter((x) => x && !/^[A-Z]{1,3}$/.test(x))
}

export function isTracked(o: Option): boolean {
  if (typeof o.stock_tracked === 'boolean') return o.stock_tracked
  return !/not tracked/i.test(o.stock || '')
}

/** "Laura Mäkinen (F&B Manager)" → { name, role } */
export function splitPerson(s: string | null | undefined): { name: string; role: string } {
  const m = /^(.*?)\s*\((.*)\)\s*$/.exec(s || '')
  return m ? { name: m[1], role: m[2] } : { name: s || '', role: '' }
}

export function eurDiff(v: number): string {
  if (Math.abs(v) < 0.005) return t('same_price')
  const loc = getLang() === 'fi' ? 'fi-FI' : 'en-GB'
  const s = new Intl.NumberFormat(loc, { style: 'currency', currency: 'EUR', minimumFractionDigits: 2 }).format(Math.abs(v))
  return `${v > 0 ? '+' : '−'}${s}`
}

/** Who decides on a pending approval: the gate's named approver, else the customer's first mandate approver. */
export function approverOf(a: Approval, customers: Customer[]): string {
  return a.order?.approval?.approver || a.approver || customers.find((c) => c.id === a.buyer_id)?.approvers?.[0] || 'Approver'
}

const HEL = 'Europe/Helsinki'

/** Parse ISO datetimes, including offsets without a colon ("+0200") that Safari rejects. */
export function parseDt(v: string | null | undefined): Date | null {
  if (!v) return null
  const d = new Date(v.replace(/([+-]\d{2})(\d{2})$/, '$1:$2'))
  return Number.isNaN(d.getTime()) ? null : d
}

/** ISO datetime → "Sun 15 Nov 17:00" / "su 15.11. klo 17.00" in Finnish time. */
export function cutoffText(v: string | null | undefined): string {
  if (!v) return ''
  const d = parseDt(v)
  if (!d) return v
  if (getLang() === 'fi') {
    const dd = d.toLocaleDateString('fi-FI', { weekday: 'short', day: 'numeric', month: 'numeric', timeZone: HEL }).replace(/\.?$/, '.')
    const tt = d.toLocaleTimeString('fi-FI', { hour: '2-digit', minute: '2-digit', timeZone: HEL })
    return `${dd} klo ${tt}`
  }
  const dayPart = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: HEL })
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: HEL })
  return `${dayPart} ${time}`
}

/** Milliseconds until an ISO datetime (NaN if unparseable). */
export function msUntil(v: string | null | undefined, now = Date.now()): number {
  const d = parseDt(v)
  return d ? d.getTime() - now : NaN
}

/** 7_800_000 → "2 h 10 min" */
export function durationText(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60000))
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  if (h < 48) return `${h} h ${m % 60} min`
  return t('days', { n: Math.round(h / 24) })
}

/** "Barilla Spaghetti n.5 durum wheat pasta 1kgx15" → "Barilla Spaghetti n.5" */
export function shortName(v: string | undefined, words = 3): string {
  const w = (v || '').split(/\s+/).filter(Boolean)
  return w.length > words ? w.slice(0, words).join(' ') : w.join(' ')
}

/** Number in "in stock (384)" */
export function stockCount(stock: string | undefined): string | null {
  const m = /\(([\d.,]+)\)/.exec(stock || '')
  return m ? m[1] : null
}
