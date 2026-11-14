import { AlertTriangle, Check, Inbox, ShieldCheck, Sparkles, UserCheck, X } from 'lucide-react'
import { useState } from 'react'
import { Spinner } from '../components/ToolSteps'
import { cx } from '../components/ui'
import { ago, day, eur, num } from '../lib/format'
import type { Approval } from '../types'
import { approverOf, splitPerson } from './format'
import type { Customer } from './types'

interface Props {
  approvals: Approval[]
  customers: Customer[]
  onDecide: (a: Approval, approver: string, approve: boolean, note: string) => Promise<boolean>
}

export function Approvals({ approvals, customers, onDecide }: Props) {
  const [leaving, setLeaving] = useState<Record<string, boolean>>({})
  const people = [...new Set(approvals.map((a) => approverOf(a, customers)))]

  return (
    <div className="mx-auto w-full max-w-4xl px-8 py-8">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Approvals</h1>
          <p className="mt-1 max-w-2xl text-[14px] text-slate-500">
            Orders above a customer’s own limit wait here for the person their purchasing mandate names. Nothing is sent to the warehouse until they decide.
          </p>
        </div>
        {people.length > 0 && (
          <div className="flex shrink-0 -space-x-2">
            {people.map((p) => (
              <div key={p} title={p} className="grid h-9 w-9 place-items-center rounded-full bg-[#eef3fc] text-[12px] font-semibold text-[#0b2f6b] ring-2 ring-white">
                {splitPerson(p).name.split(' ').map((w) => w[0]).join('').slice(0, 2)}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-6 space-y-4">
        {approvals.map((a) => (
          <ApprovalCard key={a.id} a={a} customers={customers} leaving={!!leaving[a.id]}
            onDecide={async (approver, approve, note) => {
              const ok = await onDecide(a, approver, approve, note)
              if (ok) setLeaving((l) => ({ ...l, [a.id]: true }))
            }} />
        ))}
        {approvals.length === 0 && (
          <div className="rounded-2xl bg-white px-8 py-14 text-center shadow-sm ring-1 ring-slate-200/80">
            <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-full bg-emerald-50 text-emerald-600"><Inbox className="h-6 w-6" /></div>
            <div className="text-[16px] font-semibold text-slate-800">Nothing waiting for approval</div>
            <p className="mx-auto mt-1 max-w-md text-[13.5px] text-slate-500">
              When an order is above the customer’s limit or needs a second look, it shows up here with plain-language reasons.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function ApprovalCard({ a, customers, leaving, onDecide }: {
  a: Approval; customers: Customer[]; leaving: boolean
  onDecide: (approver: string, approve: boolean, note: string) => Promise<void>
}) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const o = a.order
  const lines = o?.quote?.lines || []
  const cust = customers.find((c) => c.id === a.buyer_id)
  const approver = approverOf(a, customers)
  const who = splitPerson(approver)
  const reasons = a.reasons?.length ? a.reasons
    : (o?.decision?.findings || []).filter((f) => f.outcome !== 'AUTO').map((f) => f.message || '')
  const via = (o?.rationale || '').includes('Aimo Assistant')

  const go = async (approve: boolean) => {
    setBusy(approve ? 'approve' : 'reject')
    await onDecide(approver, approve, note.trim())
    setBusy(null)
  }

  return (
    <div className={cx('anim-in overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-amber-200', leaving && 'anim-out')}>
      <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[11.5px] font-semibold text-amber-800">Needs your approval</span>
            {via && <span className="flex items-center gap-1 text-[11.5px] text-slate-400"><Sparkles className="h-3 w-3" />via Aimo Assistant</span>}
          </div>
          <div className="mt-1.5 text-[17px] font-semibold text-slate-900">{cust?.name || a.buyer_id}</div>
          <div className="text-[12.5px] text-slate-500">
            {cust?.contact ? `Ordered by ${cust.contact.name}` : 'Order'}
            {o?.quote?.deliver_by && ` · delivery ${day(o.quote.deliver_by)}`} · {ago(a.created)}
            <span className="ml-1 font-mono text-[11px] text-slate-400">{a.order_id}</span>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-2xl font-semibold tabular-nums text-slate-900">{eur(o?.total)}</div>
          <div className="text-[11.5px] text-slate-400">excl. VAT</div>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-6 px-6 py-4">
        <div className="col-span-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{lines.length} line{lines.length === 1 ? '' : 's'}</div>
          <div className="max-h-60 divide-y divide-slate-100 overflow-y-auto pr-1">
            {lines.map((l, i) => (
              <div key={i} className="flex items-baseline justify-between gap-3 py-1.5 text-[13px]">
                <span className="min-w-0 truncate text-slate-700" title={l.name}>{l.name || l.product_id}</span>
                <span className="shrink-0 text-[12px] tabular-nums text-slate-400">{num(l.units)} {(l.sales_unit || '').toLowerCase()}</span>
                <span className="w-20 shrink-0 text-right font-medium tabular-nums text-slate-800">{eur(l.line_total)}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="col-span-2">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Why it needs you</div>
          <ul className="space-y-1.5">
            {reasons.map((r, i) => (
              <li key={i} className="flex gap-2 rounded-lg bg-amber-50 px-2.5 py-2 text-[12.5px] leading-snug text-amber-900">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />{r}
              </li>
            ))}
            {reasons.length === 0 && <li className="text-[12.5px] text-slate-500">Above the customer’s approval limit.</li>}
          </ul>
        </div>
      </div>

      <div className="flex items-center gap-3 border-t border-slate-100 bg-slate-50/70 px-6 py-3.5">
        <div className="flex shrink-0 items-center gap-2 text-[12.5px] text-slate-600">
          <UserCheck className="h-4 w-4 text-[#0b2f6b]" />
          <span><span className="font-semibold text-slate-800">{who.name}</span>{who.role && <span className="text-slate-400"> · {who.role}</span>}</span>
        </div>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note for the kitchen (optional)"
          className="min-w-0 flex-1 rounded-lg border-0 bg-white px-3 py-2 text-[13px] text-slate-800 ring-1 ring-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-[#1f4fbf]/40 focus:outline-none" />
        <button type="button" disabled={!!busy || leaving} onClick={() => go(false)}
          className="flex items-center gap-1.5 rounded-lg bg-white px-3.5 py-2 text-[13px] font-semibold text-red-600 ring-1 ring-red-200 transition hover:bg-red-50 disabled:opacity-60">
          {busy === 'reject' ? <Spinner /> : <X className="h-4 w-4" />} Reject
        </button>
        <button type="button" disabled={!!busy || leaving} onClick={() => go(true)}
          className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-[13px] font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-60">
          {busy === 'approve' ? <Spinner /> : <Check className="h-4 w-4" />} Approve
        </button>
      </div>
      <div className="flex items-center gap-1.5 px-6 pb-3 text-[11px] text-slate-400">
        <ShieldCheck className="h-3.5 w-3.5" /> Your decision is recorded in the tamper-evident audit trail; on approval Valio signs the order confirmation.
      </div>
    </div>
  )
}
