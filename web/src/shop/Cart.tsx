import {
  AlertTriangle, Bell, BookmarkPlus, Check, CheckCircle2, ChevronDown, Clock, Plus, ShieldCheck, Tag, Trash2, X, XCircle,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Spinner } from '../components/ToolSteps'
import { cx } from '../components/ui'
import { day, eur, isNum, num } from '../lib/format'
import { cleanAllergens, cutoffText, durationText, eurDiff, isTracked, msUntil, qtyText, shortName } from './format'
import type { Cart as CartT, Check as CheckT, Line, OrderInfo, Option, Plan } from './types'

export interface CartActions {
  onSelect: (key: string, option: number) => Promise<void>
  onRemove: (key: string) => Promise<void>
  onConfirm: () => Promise<void>
  onReference: (reference: string) => Promise<void>
  onSaveTemplate: (name: string) => Promise<void>
  onNotify: (key: string) => Promise<void>
}

// ------------------------------------------------------------------ step 3: products
export function Products({ cart, plan, busy, actions }: { cart: CartT; plan?: Plan | null; busy: boolean; actions: CartActions }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={cx('min-h-0 flex-1 overflow-y-auto px-8 py-5 transition-opacity', busy && 'pointer-events-none opacity-50')}>
        <Header cart={cart} onReference={actions.onReference} />
        {plan && <PlanSummary plan={plan} />}
        <div className="mt-3 space-y-2">
          {cart.lines.map((l) => <LineRow key={l.key} line={l} actions={actions} />)}
        </div>
      </div>
      <Footer cart={cart} busy={busy} onConfirm={actions.onConfirm} />
    </div>
  )
}

function Header({ cart, onReference }: { cart: CartT; onReference: (r: string) => Promise<void> }) {
  const [notes, setNotes] = useState(false)
  const [refOpen, setRefOpen] = useState(!!cart.reference)
  const link = 'text-[12.5px] font-medium text-[#1f4fbf] hover:underline'
  return (
    <div>
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="min-w-0 truncate text-[19px] font-semibold text-slate-900">{cart.title || 'Your cart'}</h2>
        {cart.deliver_by && <span className="shrink-0 text-[13px] text-slate-500">Delivery <span className="font-medium text-slate-700">{day(cart.deliver_by)}</span></span>}
      </div>
      <div className="mt-1 flex items-center gap-4">
        {(cart.assumptions?.length || 0) > 0 && (
          <button type="button" onClick={() => setNotes(!notes)} className={link}>{notes ? 'Hide notes' : `Notes (${cart.assumptions!.length})`}</button>
        )}
        {refOpen
          ? <ReferenceInput key={cart.reference || ''} value={cart.reference || ''} onSave={onReference} />
          : <button type="button" onClick={() => setRefOpen(true)} className={cx(link, 'flex items-center gap-1')}><Plus className="h-3.5 w-3.5" />Add reference</button>}
      </div>
      {notes && (
        <ul className="mt-2 space-y-1 rounded-xl bg-white px-4 py-2.5 text-[12.5px] leading-snug text-slate-600 ring-1 ring-slate-200/80">
          {cart.assumptions!.map((a, i) => <li key={i}>· {a}</li>)}
        </ul>
      )}
    </div>
  )
}

/** Valio's "User reference": free text that travels with the order. */
function ReferenceInput({ value, onSave }: { value: string; onSave: (r: string) => Promise<void> }) {
  const [v, setV] = useState(value)
  return (
    <label className="flex w-72 items-center gap-1.5 rounded-lg bg-white px-2 py-1 ring-1 ring-slate-200 focus-within:ring-2 focus-within:ring-[#1f4fbf]/40">
      <Tag className="h-3.5 w-3.5 shrink-0 text-slate-400" />
      <input autoFocus={!value} value={v} onChange={(e) => setV(e.target.value)} maxLength={80} placeholder="Your reference, e.g. Saturday party"
        onBlur={() => { if (v.trim() !== value.trim()) void onSave(v.trim()) }}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
        className="min-w-0 flex-1 border-0 bg-transparent text-[12.5px] text-slate-800 placeholder:text-slate-300 focus:outline-none" />
    </label>
  )
}

function PlanSummary({ plan }: { plan: Plan }) {
  const [open, setOpen] = useState(false)
  const changes = plan.changes || []
  return (
    <div className="mt-3 rounded-xl bg-emerald-50/70 px-3.5 py-2 text-[12.5px] text-emerald-800 ring-1 ring-emerald-100">
      <button type="button" disabled={!changes.length} onClick={() => setOpen(!open)} className="flex w-full items-center gap-1.5 text-left font-medium">
        <Check className="h-3.5 w-3.5" strokeWidth={3} />
        Ingredients approved by you{changes.length > 0 && <> · {changes.length} change{changes.length > 1 ? 's' : ''}</>}
        {changes.length > 0 && <ChevronDown className={cx('ml-auto h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />}
      </button>
      {open && <ul className="mt-1.5 space-y-0.5 pl-5 text-emerald-900/80">{changes.map((c, i) => <li key={i}>· {c}</li>)}</ul>}
    </div>
  )
}

function Status({ o }: { o: Option }) {
  const d = o.delivery
  const dot = (cls: string, text: string, label: ReactNode) => (
    <span className={cx('inline-flex shrink-0 items-center gap-1.5 text-[12px] font-medium', text)}>
      <span className={cx('h-2 w-2 rounded-full', cls)} />{label}
    </span>
  )
  if (/not available/i.test(o.stock || '')) return dot('bg-red-500', 'text-red-700', 'Not available')
  if (d?.on_time === false) return dot('bg-amber-500', 'text-amber-800', <>Late · {day(d.date)}</>)
  if (isTracked(o)) return dot('bg-emerald-500', 'text-emerald-700', 'In stock')
  return dot('bg-sky-500', 'text-sky-800', 'Orderable')
}

function LineRow({ line, actions, readOnly }: { line: Line; actions?: CartActions; readOnly?: boolean }) {
  const opts = line.options || []
  const sel = opts[line.selected] ?? opts[0]
  const decide = !!line.decision_needed && !readOnly
  const [openOpts, setOpenOpts] = useState<boolean | null>(null)
  const [details, setDetails] = useState(false)
  const [pending, setPending] = useState<number | null>(null)
  const showOpts = !readOnly && opts.length > 1 && (openOpts ?? decide)

  const choose = async (i: number) => {
    if (!actions || (i === line.selected && !decide)) return setOpenOpts(false)
    setPending(i)
    await actions.onSelect(line.key, i)
    setPending(null)
    setOpenOpts(false)
  }

  return (
    <div id={`line-${line.key}`} className={cx('scroll-mt-3 overflow-hidden rounded-xl bg-white ring-1 ring-slate-200/80', decide && 'border-l-4 border-amber-400')}>
      <div className="px-4 py-2.5">
        <div className="flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[11.5px] text-slate-400">
              <span className="truncate">{line.need}</span>
              {decide && <span className="shrink-0 rounded-full bg-amber-100 px-1.5 py-px font-semibold text-amber-800">Choose one</span>}
            </div>
            {sel
              ? <div className="truncate text-[14px] font-semibold text-slate-900" title={sel.name}>{sel.name}</div>
              : <div className="flex items-center gap-1.5 text-[13px] text-red-700"><XCircle className="h-3.5 w-3.5" />{line.problem || 'No product found'}</div>}
          </div>
          {sel && (
            <>
              <div className="shrink-0 pt-4 text-[13px] tabular-nums text-slate-500">{qtyText(sel)}</div>
              <div className="w-20 shrink-0 pt-3.5 text-right text-[14.5px] font-semibold tabular-nums text-slate-900">{eur(sel.total)}</div>
            </>
          )}
        </div>

        {line.replaces && (
          <div className="mt-0.5 truncate text-[12px] text-slate-500">Replaces <span className="line-through">{line.replaces.name}</span></div>
        )}

        {sel && (
          <div className="mt-1 flex items-center gap-2.5">
            <Status o={sel} />
            {sel.usual && <span className="shrink-0 rounded-full bg-emerald-50 px-1.5 py-px text-[11px] font-medium text-emerald-700">Your usual</span>}
            {sel.why && <span className="min-w-0 flex-1 truncate text-[12px] text-slate-400" title={sel.why}>{sel.why}</span>}
            {!sel.why && <span className="flex-1" />}
            {!readOnly && opts.length > 1 && (
              <button type="button" onClick={() => setOpenOpts(!showOpts)}
                className={cx('shrink-0 rounded-md px-2 py-0.5 text-[12px] font-semibold ring-1 transition',
                  decide ? 'bg-amber-50 text-amber-800 ring-amber-200' : 'text-[#1f4fbf] ring-slate-200 hover:bg-[#eef3fc]')}>
                {opts.length} options
              </button>
            )}
            {!readOnly && (
              <button type="button" onClick={() => setDetails(!details)} className="shrink-0 text-[12px] text-slate-400 hover:text-slate-700">
                {details ? 'Less' : 'Details'}
              </button>
            )}
          </div>
        )}

        {details && sel && actions && <Details line={line} o={sel} actions={actions} />}
      </div>

      {showOpts && (
        <div className="space-y-1.5 border-t border-slate-100 bg-slate-50/70 px-3 py-2.5">
          {opts.map((o, i) => {
            const on = i === line.selected && !decide
            const diff = sel ? o.total - sel.total : 0
            return (
              <button key={`${o.product_id}-${i}`} type="button" disabled={pending !== null} onClick={() => choose(i)}
                className={cx('flex w-full items-center gap-3 rounded-lg bg-white px-3 py-2 text-left ring-1 transition',
                  on ? 'ring-2 ring-[#1f4fbf]/60' : 'ring-slate-200 hover:ring-[#1f4fbf]/40')}>
                <span className={cx('grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-bold',
                  on ? 'bg-[#0b2f6b] text-white' : 'bg-slate-100 text-slate-600')}>
                  {pending === i ? <Spinner className="h-2.5 w-2.5" /> : on ? <Check className="h-3 w-3" strokeWidth={3} /> : i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-slate-800">{o.name}</span>
                  <span className="block truncate text-[12px] text-slate-500">{qtyText(o)}{o.why ? ` · ${o.why}` : ''}</span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block text-[13px] font-semibold tabular-nums text-slate-900">{eur(o.total)}</span>
                  {i !== line.selected && <span className={cx('block text-[11.5px] tabular-nums', diff < -0.005 ? 'text-emerald-600' : 'text-slate-400')}>{eurDiff(diff)}</span>}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Details({ line, o, actions }: { line: Line; o: Option; actions: CartActions }) {
  const [busy, setBusy] = useState(false)
  const allergens = cleanAllergens(o.allergens)
  const facts = [
    o.price_per,
    o.delivery?.date ? `Delivery ${day(o.delivery.date)}${o.delivery.confirmed === false ? ' (estimate)' : ''}` : null,
    o.order_by ? `Order by ${cutoffText(o.order_by)}` : null,
    isNum(o.co2_kg) ? `${num(o.co2_kg)} kg CO₂` : null,
    isTracked(o) ? o.stock : null,
    allergens.length ? `Contains ${allergens.join(', ')}` : null,
  ].filter(Boolean)
  return (
    <div className="mt-2 border-t border-slate-100 pt-2 text-[12px] text-slate-500">
      <div>{facts.join(' · ')}</div>
      {(o.notes || []).map((n, i) => (
        <div key={i} className="mt-1 flex gap-1.5 text-amber-700"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{n}</div>
      ))}
      <div className="mt-1.5 flex items-center gap-4">
        {line.replaces && (line.notify
          ? <span className="flex items-center gap-1 font-medium text-emerald-700"><Bell className="h-3.5 w-3.5" />We’ll notify you ✓</span>
          : (
            <button type="button" disabled={busy} onClick={async () => { setBusy(true); await actions.onNotify(line.key); setBusy(false) }}
              className="flex items-center gap-1 font-medium text-[#1f4fbf] hover:underline">
              <Bell className="h-3.5 w-3.5" />Notify me when {shortName(line.replaces.name)} is back
            </button>
          ))}
        <button type="button" disabled={busy} onClick={async () => { setBusy(true); await actions.onRemove(line.key); setBusy(false) }}
          className="ml-auto flex items-center gap-1 text-slate-400 hover:text-red-600">
          <Trash2 className="h-3.5 w-3.5" />Remove
        </button>
      </div>
    </div>
  )
}

/** Re-render every 30 s so relative times stay fresh. */
function useNow(ms = 30000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms)
    return () => window.clearInterval(id)
  }, [ms])
  return now
}

function CheckChip({ c }: { c: CheckT }) {
  const tone = c.level === 'ok' ? 'text-emerald-700' : c.level === 'warn' ? 'text-amber-800' : 'text-red-700'
  const Icon = c.level === 'ok' ? CheckCircle2 : c.level === 'warn' ? AlertTriangle : XCircle
  return <span className={cx('inline-flex items-center gap-1 text-[12px] font-medium', tone)}><Icon className="h-3.5 w-3.5" />{c.label}</span>
}

function Footer({ cart, busy, onConfirm }: { cart: CartT; busy: boolean; onConfirm: () => Promise<void> }) {
  const now = useNow()
  const [confirming, setConfirming] = useState(false)
  const t = cart.totals || {}
  const total = isNum(t.total) ? t.total : cart.lines.reduce((s, l) => s + (l.options[l.selected]?.total || 0), 0)
  const open = t.choices_open || 0
  const checks = (cart.checks || []).slice(0, 3)
  const block = checks.find((c) => c.level === 'block')
  const approval = checks.some((c) => c.id === 'spend' && c.level === 'warn')
  const ms = msUntil(t.order_by, now)
  const soon = ms < 3 * 3600_000
  const sub = [isNum(t.total_with_tax) ? `${eur(t.total_with_tax)} incl. VAT` : null, isNum(t.per_portion) ? `${eur(t.per_portion)} / portion` : null].filter(Boolean)

  const firstOpen = () => {
    const l = cart.lines.find((x) => x.decision_needed)
    if (l) document.getElementById(`line-${l.key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="shrink-0 border-t border-slate-200 bg-white px-8 py-3">
      {checks.length > 0 && <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1">{checks.map((c) => <CheckChip key={c.id} c={c} />)}</div>}
      <div className="flex items-center gap-5">
        <div>
          <div className="text-[24px] font-semibold leading-tight tabular-nums text-slate-900">{eur(total)} <span className="text-[12px] font-normal text-slate-400">excl. VAT</span></div>
          {sub.length > 0 && <div className="text-[12px] tabular-nums text-slate-500">{sub.join(' · ')}</div>}
        </div>
        <div className="ml-auto flex items-center gap-4">
          {open > 0 ? (
            <button type="button" onClick={firstOpen} className="text-[12.5px] font-medium text-amber-700 hover:underline">
              Choose {open} option{open > 1 ? 's' : ''} first
            </button>
          ) : t.order_by && !Number.isNaN(ms) && (
            <span className={cx('flex items-center gap-1 text-[12px]', soon ? 'font-medium text-amber-700' : 'text-slate-500')}>
              <Clock className="h-3.5 w-3.5" />
              {ms <= 0 ? 'Cut-off passed' : <>Confirm before {cutoffText(t.order_by)}{soon && ` · in ${durationText(ms)}`}</>}
            </span>
          )}
          <button type="button" disabled={busy || open > 0 || confirming || !!block}
            onClick={async () => { setConfirming(true); await onConfirm(); setConfirming(false) }}
            className={cx('flex items-center gap-2 rounded-xl px-6 py-2.5 text-[14.5px] font-semibold text-white shadow-sm transition disabled:bg-slate-300 disabled:shadow-none',
              approval ? 'bg-amber-600 hover:bg-amber-700' : 'bg-emerald-600 hover:bg-emerald-700')}>
            {confirming && <Spinner className="h-4 w-4" />}
            {block ? block.label : approval ? 'Send for approval' : 'Confirm order'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ step 4: order
export function OrderView({ cart, order, onSaveTemplate, onNew }: {
  cart: CartT | null; order: OrderInfo; onSaveTemplate: (name: string) => Promise<void>; onNew: () => void
}) {
  const s = (order.status || '').toUpperCase()
  const tone = s === 'CONFIRMED' ? 'green' : s === 'PENDING_APPROVAL' ? 'amber' : 'red'
  const reasons = order.reasons || []
  const facts = [
    order.order_id,
    order.delivery ? `Delivery ${day(order.delivery)}` : null,
    isNum(order.total) ? `${eur(order.total)} excl. VAT` : null,
    order.reference ? `Ref. ${order.reference}` : null,
  ].filter(Boolean)
  return (
    <div className="h-full overflow-y-auto px-8 py-6">
      <div className={cx('anim-in rounded-2xl px-6 py-5 ring-1',
        tone === 'green' && 'bg-emerald-50 ring-emerald-200', tone === 'amber' && 'bg-amber-50 ring-amber-200', tone === 'red' && 'bg-red-50 ring-red-200')}>
        <div className="flex items-center gap-4">
          <div className={cx('grid h-11 w-11 shrink-0 place-items-center rounded-full text-white',
            tone === 'green' && 'bg-emerald-600', tone === 'amber' && 'bg-amber-500', tone === 'red' && 'bg-red-500')}>
            {tone === 'green' ? <Check className="h-6 w-6" strokeWidth={3} /> : tone === 'amber' ? <Clock className="h-6 w-6" /> : <X className="h-6 w-6" strokeWidth={3} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[19px] font-semibold text-slate-900">
              {tone === 'green' ? 'Order confirmed' : tone === 'amber' ? `Waiting for ${order.approver || 'your approver'}` : 'Order not accepted'}
            </div>
            <div className="text-[13px] text-slate-600">{facts.join(' · ')}</div>
          </div>
          {tone === 'green' && order.signed && (
            <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-white px-3 py-1 text-[12.5px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
              <ShieldCheck className="h-4 w-4" />Signed by Valio
            </span>
          )}
        </div>
        {tone !== 'green' && reasons.length > 0 && (
          <ul className="mt-3 space-y-1 pl-[60px] text-[13px] leading-snug text-slate-700">
            {reasons.map((r, i) => <li key={i}>· {r}</li>)}
          </ul>
        )}
        {order.note && <div className="mt-2 pl-[60px] text-[13px] italic text-slate-600">“{order.note}”</div>}
        <div className="mt-4 flex items-center gap-3 pl-[60px]">
          {tone !== 'red' && cart && <SaveTemplate cart={cart} onSave={onSaveTemplate} />}
          <button type="button" onClick={onNew}
            className="flex items-center gap-1.5 rounded-lg bg-[#0b2f6b] px-3.5 py-1.5 text-[13px] font-semibold text-white hover:bg-[#123d86]">
            <Plus className="h-4 w-4" />New order
          </button>
        </div>
      </div>

      {cart && (
        <div className="mt-5">
          <div className="mb-2 text-[12px] font-semibold uppercase tracking-wider text-slate-400">{cart.lines.length} products</div>
          <div className="divide-y divide-slate-100 rounded-xl bg-white px-4 ring-1 ring-slate-200/80">
            {cart.lines.map((l) => {
              const o = l.options[l.selected]
              if (!o) return null
              return (
                <div key={l.key} className="flex items-baseline gap-4 py-2 text-[13px]">
                  <span className="min-w-0 flex-1 truncate text-slate-800">{o.name}</span>
                  <span className="shrink-0 tabular-nums text-slate-500">{qtyText(o)}</span>
                  <span className="w-20 shrink-0 text-right font-medium tabular-nums text-slate-900">{eur(o.total)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function SaveTemplate({ cart, onSave }: { cart: CartT; onSave: (name: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(cart.title || '')
  const [busy, setBusy] = useState(false)
  if (cart.saved_template) {
    return <span className="flex items-center gap-1.5 text-[13px] font-medium text-emerald-700"><Check className="h-4 w-4" />Saved as order template</span>
  }
  if (!editing) {
    return (
      <button type="button" onClick={() => setEditing(true)}
        className="flex items-center gap-1.5 rounded-lg bg-white px-3.5 py-1.5 text-[13px] font-semibold text-[#0b2f6b] ring-1 ring-slate-200 hover:bg-[#eef3fc]">
        <BookmarkPlus className="h-4 w-4" />Save as order template
      </button>
    )
  }
  const go = async () => {
    if (!name.trim()) return
    setBusy(true)
    await onSave(name.trim())
    setBusy(false)
  }
  return (
    <div className="flex items-center gap-2">
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={80}
        onKeyDown={(e) => { if (e.key === 'Enter') void go(); if (e.key === 'Escape') setEditing(false) }}
        className="w-64 rounded-lg border-0 bg-white px-3 py-1.5 text-[13px] text-slate-800 ring-1 ring-slate-300 focus:ring-2 focus:ring-[#1f4fbf]/40 focus:outline-none" />
      <button type="button" disabled={busy || !name.trim()} onClick={go}
        className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-[13px] font-semibold text-[#0b2f6b] ring-1 ring-slate-300 disabled:opacity-60">
        {busy && <Spinner className="h-3 w-3" />}Save
      </button>
    </div>
  )
}
