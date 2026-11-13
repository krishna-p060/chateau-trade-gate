import { Bot, Check, Inbox, ListOrdered, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ago, day, eur, num } from '../lib/format'
import { approverFor, shortBuyer } from '../lib/mandates'
import type { Approval, Buyer, Order } from '../types'
import { Spinner } from './ToolSteps'
import { Badge, Card, Empty, ReasonList, SectionTitle, SignedBadge, StatusPill, cx } from './ui'

interface Props {
  approvals: Approval[]
  orders: Order[]
  buyers: Buyer[]
  onDecide: (a: Approval, approver: string, approve: boolean, note: string) => Promise<boolean>
  onOpenAudit: (ref: string) => void
}

export function ApprovalInbox({ approvals, orders, buyers, onDecide, onOpenAudit }: Props) {
  // keep decided cards around briefly so they can animate out
  const [leaving, setLeaving] = useState<Record<string, Approval>>({})
  const shown = [...approvals.filter((a) => !leaving[a.id]), ...Object.values(leaving)]
    .sort((a, b) => (b.created || '').localeCompare(a.created || ''))

  const decide = async (a: Approval, approver: string, approve: boolean, note: string) => {
    const ok = await onDecide(a, approver, approve, note)
    if (ok) {
      setLeaving((l) => ({ ...l, [a.id]: a }))
      window.setTimeout(() => setLeaving((l) => {
        const n = { ...l }
        delete n[a.id]
        return n
      }), 750)
    }
  }

  const recent = [...orders].sort((a, b) => (b.updated || b.created || '').localeCompare(a.updated || a.created || '')).slice(0, 12)

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto pb-2 pl-1">
      <div>
        <SectionTitle icon={<Inbox className="h-4 w-4" />} right={approvals.length > 0 && (
          <span className="rounded-full bg-amber-500 px-2 py-0.5 text-[11px] font-bold text-white">{approvals.length}</span>
        )}>Approval inbox</SectionTitle>
        <div className="space-y-3">
          {shown.map((a) => (
            <ApprovalCard key={a.id} a={a} buyers={buyers} leaving={!!leaving[a.id]} onDecide={decide} onOpenAudit={onOpenAudit} />
          ))}
          {shown.length === 0 && (
            <Card><Empty icon={<Check className="h-8 w-8" />} title="Nothing waiting for you">Orders outside an agent’s mandate land here with plain-language reasons.</Empty></Card>
          )}
        </div>
      </div>

      <div>
        <SectionTitle icon={<ListOrdered className="h-4 w-4" />}>Recent orders</SectionTitle>
        <Card className="divide-y divide-slate-100">
          {recent.map((o) => <OrderRow key={o.id} o={o} buyers={buyers} onOpenAudit={onOpenAudit} />)}
          {recent.length === 0 && <Empty title="No orders yet" />}
        </Card>
      </div>
    </div>
  )
}

function ApprovalCard({ a, buyers, leaving, onDecide, onOpenAudit }: {
  a: Approval; buyers: Buyer[]; leaving: boolean
  onDecide: (a: Approval, approver: string, approve: boolean, note: string) => Promise<void>
  onOpenAudit: (ref: string) => void
}) {
  const [approver, setApprover] = useState(approverFor(a.buyer_id))
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const o = a.order
  const lines = o?.quote?.lines || []
  const reasons = a.reasons?.length ? a.reasons : (o?.decision?.findings || []).filter((f) => f.outcome !== 'AUTO').map((f) => f.message || '')

  const go = async (approve: boolean) => {
    if (!approver.trim()) return
    setBusy(approve ? 'approve' : 'reject')
    await onDecide(a, approver.trim(), approve, note.trim())
    setBusy(null)
  }

  return (
    <Card className={cx('anim-in overflow-hidden ring-amber-300/70', leaving && 'anim-out')}>
      <div className="h-1 bg-amber-400" />
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Badge tone="amber">Needs approval</Badge>
              <span className="truncate text-[12.5px] font-semibold text-slate-700">{shortBuyer(a.buyer_id, buyers)}</span>
            </div>
            <button type="button" onClick={() => onOpenAudit(a.order_id)} className="mt-1 font-mono text-[11px] text-slate-400 hover:text-valio-600 hover:underline">
              {a.order_id} · {ago(a.created)}
            </button>
          </div>
          <div className="text-right">
            <div className="text-xl font-bold tabular-nums text-slate-900">{eur(o?.total)}</div>
            <div className="text-[11px] text-slate-400">excl. VAT</div>
          </div>
        </div>

        {lines.length > 0 && (
          <div className="mt-3 space-y-1 rounded-lg bg-slate-50 p-2.5 ring-1 ring-slate-200/70">
            {lines.map((l, i) => (
              <div key={i} className="text-[12.5px]">
                <div className="truncate font-medium text-slate-800" title={l.name}>{l.name || l.product_id}</div>
                <div className="flex justify-between text-[11.5px] text-slate-500">
                  <span className="tabular-nums">{num(l.units)} {l.sales_unit} × {eur(l.unit_price)}</span>
                  <span className={cx(l.meets_deadline === false && 'font-semibold text-amber-700')}>
                    delivery {day(l.earliest_delivery)}{l.earliest_delivery_confirmed === false ? ' (est.)' : ''}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {o?.rationale && (
          <div className="mt-3 flex gap-2 text-[12.5px] text-slate-600">
            <Bot className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
            <span className="italic">“{o.rationale}”</span>
          </div>
        )}

        {reasons.length > 0 && (
          <div className="mt-3">
            <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">Why it needs you</div>
            <ReasonList reasons={reasons} />
          </div>
        )}

        <div className="mt-3 grid grid-cols-1 gap-2">
          <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Approver"
            className="w-full rounded-lg border-0 bg-white px-2.5 py-1.5 text-[12.5px] text-slate-800 ring-1 ring-slate-200 focus:ring-2 focus:ring-valio-500 focus:outline-none" />
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)"
            onKeyDown={(e) => { if (e.key === 'Enter' && !busy) go(true) }}
            className="w-full rounded-lg border-0 bg-white px-2.5 py-1.5 text-[12.5px] text-slate-800 ring-1 ring-slate-200 focus:ring-2 focus:ring-valio-500 focus:outline-none" />
        </div>
        <div className="mt-3 flex gap-2">
          <button type="button" disabled={!!busy || leaving || !approver.trim()} onClick={() => go(true)}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-[13px] font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-60">
            {busy === 'approve' ? <Spinner /> : <Check className="h-4 w-4" />} Approve
          </button>
          <button type="button" disabled={!!busy || leaving || !approver.trim()} onClick={() => go(false)}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-white px-3 py-2 text-[13px] font-semibold text-red-600 ring-1 ring-red-200 transition hover:bg-red-50 disabled:opacity-60">
            {busy === 'reject' ? <Spinner /> : <X className="h-4 w-4" />} Reject
          </button>
        </div>
      </div>
    </Card>
  )
}

function OrderRow({ o, buyers, onOpenAudit }: { o: Order; buyers: Buyer[]; onOpenAudit: (ref: string) => void }) {
  // flash the row when its status changes (e.g. approved)
  const prev = useRef(o.status)
  const [flash, setFlash] = useState(false)
  useEffect(() => {
    if (prev.current !== o.status) {
      prev.current = o.status
      setFlash(true)
      const t = window.setTimeout(() => setFlash(false), 1700)
      return () => window.clearTimeout(t)
    }
  }, [o.status])
  const first = o.quote?.lines?.[0]
  const more = (o.quote?.lines?.length || 0) - 1
  return (
    <button type="button" onClick={() => onOpenAudit(o.id)} className={cx('block w-full px-3.5 py-2.5 text-left transition hover:bg-slate-50', flash && 'flash')}>
      <div className="flex items-center justify-between gap-2">
        <StatusPill status={o.status} order={o} />
        <span className="text-[13px] font-bold tabular-nums text-slate-900">{eur(o.total)}</span>
      </div>
      <div className="mt-1 truncate text-[12.5px] text-slate-700" title={first?.name}>
        {first ? `${num(first.units)} × ${first.name}` : o.quote_id}{more > 0 ? ` +${more}` : ''}
      </div>
      <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-slate-400">
        <span>{shortBuyer(o.buyer_id, buyers)} · {ago(o.updated || o.created)}</span>
        {o.confirmation_jws && <SignedBadge label="Signed confirmation" />}
      </div>
    </button>
  )
}
