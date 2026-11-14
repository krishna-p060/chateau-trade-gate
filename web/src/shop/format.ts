import { isNum, num } from '../lib/format'
import type { Approval } from '../types'
import type { Customer, Option } from './types'

/** "1 l" → {n: 1, u: "l"}; "kg" → {n: null, u: "kg"}. */
function parsePack(pack: string | undefined): { n: number | null; u: string } {
  const p = (pack || '').trim()
  const m = /^([\d.,]+)\s*(.*)$/.exec(p)
  if (!m) return { n: null, u: p }
  return { n: Number(m[1].replace(',', '.')), u: m[2].trim() }
}

/** How much the customer is buying, in their words: "7 kg", "6 st", "10 × 1 l". */
export function qtyText(o: Option): string {
  const units = isNum(o.units) ? num(o.units) : '—'
  const { n, u } = parsePack(o.pack)
  const su = (o.sales_unit || '').toUpperCase()
  if (su === 'KG' && (u === 'kg' || !u)) return `${units} kg`
  if (su === 'L' && (u === 'l' || !u)) return `${units} l`
  if (n === null) return `${units} ${u || 'pcs'}`
  return `${units} × ${o.pack}`
}

/** Total content delivered, if it is consistent with the pack maths (otherwise null). */
export function coversText(o: Option, unit: string | undefined): string | null {
  if (!isNum(o.delivered_qty) || !unit || unit === 'unit') return null
  const { n, u } = parsePack(o.pack)
  if (n === null || u !== unit) return null
  if ((o.sales_unit || '').toUpperCase() === 'KG' || (o.sales_unit || '').toUpperCase() === 'L') return null
  const expected = n * o.units
  if (Math.abs(expected - o.delivered_qty) / Math.max(expected, 0.001) > 0.1) return null
  return `${num(Math.round(o.delivered_qty * 10) / 10)} ${unit}`
}

export function unitLabel(u: string | undefined): string {
  return !u || u === 'unit' ? 'pcs' : u
}

/** Customer-meaningful allergens only (drops raw 2-letter codes the catalog sometimes carries). */
export function cleanAllergens(a: string[] | undefined): string[] {
  return (a || []).filter((x) => x && !/^[A-Z]{1,3}$/.test(x))
}

export function isTracked(o: Option): boolean {
  if (typeof o.stock_tracked === 'boolean') return o.stock_tracked
  return !/not tracked/i.test(o.stock || '')
}

export function firstName(s: string | undefined): string {
  return (s || '').split(' ')[0]
}

/** "Laura Mäkinen (F&B Manager)" → { name, role } */
export function splitPerson(s: string | null | undefined): { name: string; role: string } {
  const m = /^(.*?)\s*\((.*)\)\s*$/.exec(s || '')
  return m ? { name: m[1], role: m[2] } : { name: s || '', role: '' }
}

const eurSigned = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2 })
export function eurDiff(v: number): string {
  if (Math.abs(v) < 0.005) return 'same price'
  return `${v > 0 ? '+' : '−'}${eurSigned.format(Math.abs(v))}`
}

/** Who decides on a pending approval: the gate's named approver, else the customer's first mandate approver. */
export function approverOf(a: Approval, customers: Customer[]): string {
  return a.order?.approval?.approver || a.approver || customers.find((c) => c.id === a.buyer_id)?.approvers?.[0] || 'Approver'
}
