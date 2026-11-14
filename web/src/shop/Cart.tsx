import {
  AlertTriangle, CalendarCheck, Check, CheckCircle2, ChevronDown, Clock, Leaf, Lightbulb, Package, Repeat, ShieldCheck,
  ShoppingBasket, Sparkles, Star, Truck, X, XCircle,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Spinner } from '../components/ToolSteps'
import { cx } from '../components/ui'
import { day, eur, isNum, num } from '../lib/format'
import { cleanAllergens, coversText, eurDiff, isTracked, qtyText, unitLabel } from './format'
import type { Cart as CartT, Line, OrderInfo, Option, Session } from './types'

interface Props {
  session: Session | null
  approver?: string
  onSelect: (key: string, option: number) => Promise<void>
  onRemove: (key: string) => Promise<void>
  onConfirm: () => Promise<void>
}

export function Cart({ session, approver, onSelect, onRemove, onConfirm }: Props) {
  const cart = session?.cart
  const order = session?.order
  const busy = !!session?.busy
  const locked = !!order || session?.status === 'ordering' || session?.status === 'ordered'

  if (!cart || !cart.lines?.length) return <EmptyCart busy={busy} />

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-7 pb-6 pt-5">
        <CartHeader cart={cart} />
        <div className="mt-5 space-y-3">
          {cart.lines.map((l, i) => (
            <LineCard key={l.key} line={l} index={i} locked={locked || busy} onSelect={onSelect} onRemove={onRemove} />
          ))}
        </div>
      </div>
      <Footer cart={cart} order={order ?? null} busy={busy} locked={locked} approver={approver} onConfirm={onConfirm} />
    </div>
  )
}

function EmptyCart({ busy }: { busy: boolean }) {
  return (
    <div className="grid h-full place-items-center px-10">
      <div className="max-w-sm text-center">
        <div className="relative mx-auto mb-5 h-28 w-28">
          <div className="absolute inset-0 rounded-full bg-gradient-to-br from-[#eef3fc] to-white ring-1 ring-[#d9e4f8]" />
          <div className="absolute inset-0 grid place-items-center text-[#0b2f6b]/70">
            {busy ? <Spinner className="h-8 w-8 border-[3px] text-[#1f4fbf]" /> : <ShoppingBasket className="h-11 w-11" strokeWidth={1.5} />}
          </div>
          <div className="absolute -right-1 top-3 grid h-8 w-8 place-items-center rounded-full bg-white text-emerald-600 shadow ring-1 ring-slate-200"><Leaf className="h-4 w-4" /></div>
          <div className="absolute -left-2 bottom-4 grid h-8 w-8 place-items-center rounded-full bg-white text-amber-500 shadow ring-1 ring-slate-200"><Truck className="h-4 w-4" /></div>
        </div>
        <div className="text-lg font-semibold text-slate-800">{busy ? 'Building your cart…' : 'Your cart will appear here'}</div>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-slate-500">
          {busy
            ? 'Checking live prices, stock and delivery dates with Valio Aimo.'
            : 'Tell Aimo what you are cooking. You will see every product, why it was picked, live price, stock and delivery — and nothing is ordered until you confirm.'}
        </p>
      </div>
    </div>
  )
}

function CartHeader({ cart }: { cart: CartT }) {
  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Your cart</div>
          <h2 className="mt-0.5 text-xl font-semibold leading-tight text-slate-900">{cart.title || 'Cart'}</h2>
        </div>
        {cart.deliver_by && (
          <div className="flex shrink-0 items-center gap-2 rounded-xl bg-[#eef3fc] px-3 py-2 text-[#0b2f6b]">
            <CalendarCheck className="h-4.5 w-4.5" />
            <div className="leading-tight">
              <div className="text-[10.5px] font-semibold uppercase tracking-wider opacity-70">Delivery</div>
              <div className="text-[13.5px] font-semibold">{day(cart.deliver_by)}</div>
            </div>
          </div>
        )}
      </div>
      {(cart.assumptions?.length || 0) > 0 && (
        <div className="mt-3 rounded-xl bg-white px-4 py-3 ring-1 ring-slate-200/80">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            <Lightbulb className="h-3.5 w-3.5 text-amber-500" /> I assumed
          </div>
          <ul className="space-y-1">
            {cart.assumptions!.map((a, i) => (
              <li key={i} className="flex gap-2 text-[12.5px] leading-snug text-slate-600">
                <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-400" />{a}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ line
function LineCard({ line, index, locked, onSelect, onRemove }: {
  line: Line; index: number; locked: boolean
  onSelect: (key: string, option: number) => Promise<void>; onRemove: (key: string) => Promise<void>
}) {
  const opts = line.options || []
  const sel = opts[line.selected] ?? opts[0]
  const decide = !!line.decision_needed
  const [open, setOpen] = useState(decide)
  const [pending, setPending] = useState<number | null>(null)
  const [removing, setRemoving] = useState(false)
  const covers = sel ? coversText(sel, line.unit) : null

  const choose = async (i: number) => {
    if (locked || (i === line.selected && !decide)) return
    setPending(i)
    await onSelect(line.key, i)
    setPending(null)
  }

  return (
    <div id={`line-${line.key}`} className={cx('anim-in scroll-mt-4 overflow-hidden rounded-2xl bg-white shadow-sm ring-1 transition',
      decide ? 'ring-2 ring-amber-300' : 'ring-slate-200/80', removing && 'opacity-50')}
      style={{ animationDelay: `${Math.min(index, 10) * 30}ms` }}>
      {decide && (
        <div className="flex items-center gap-1.5 bg-amber-50 px-4 py-1.5 text-[11.5px] font-semibold text-amber-800">
          <Star className="h-3.5 w-3.5" /> Your choice needed — pick one of {opts.length} options
        </div>
      )}
      <div className="px-4 pb-3 pt-3.5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-[14.5px] font-semibold text-slate-900">{line.need}</span>
              {line.dish && <span className="text-[12px] text-slate-400">{line.dish}</span>}
            </div>
            {line.replaces && (
              <div className="mt-1 flex items-center gap-1.5 text-[12px] text-slate-500">
                <Repeat className="h-3.5 w-3.5 text-amber-600" />
                Replaces <span className="line-through decoration-slate-400">{line.replaces.name}</span>
                <span className="text-amber-700">(unavailable)</span>
              </div>
            )}
          </div>
          {sel && (
            <div className="shrink-0 text-right">
              <div className="text-[16px] font-semibold tabular-nums text-slate-900">{eur(sel.total)}</div>
              {sel.price_per && <div className="text-[11.5px] tabular-nums text-slate-400">{sel.price_per}</div>}
            </div>
          )}
          {!locked && (
            <button type="button" title="Remove from cart" onClick={async () => { setRemoving(true); await onRemove(line.key); setRemoving(false) }}
              className="-mr-1.5 -mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg text-slate-300 transition hover:bg-red-50 hover:text-red-500">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {sel ? (
          <div className="mt-2.5 rounded-xl bg-slate-50/80 px-3 py-2.5 ring-1 ring-slate-100">
            <div className="flex items-start gap-2.5">
              <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white text-slate-400 ring-1 ring-slate-200"><Package className="h-4 w-4" /></div>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium leading-snug text-slate-800">{sel.name}</div>
                <div className="mt-0.5 text-[12px] text-slate-500">
                  <span className="font-medium tabular-nums text-slate-700">{qtyText(sel)}</span>
                  {covers && <span> · {covers}</span>}
                  {isNum(line.quantity) && <span className="text-slate-400"> · you need {num(line.quantity)} {unitLabel(line.unit)}</span>}
                </div>
              </div>
            </div>
            <OptionChips o={sel} />
          </div>
        ) : null}

        {line.problem && !opts.length && (
          <div className="mt-2.5 flex gap-2 rounded-xl bg-red-50 px-3 py-2 text-[12.5px] text-red-700 ring-1 ring-red-200">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" /> {line.problem}
          </div>
        )}

        {sel?.why && (
          <div className="mt-2 flex items-start gap-1.5 text-[12.5px] leading-snug text-slate-500">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#1f4fbf]/70" />
            <span><span className="font-medium text-slate-600">Why:</span> {sel.why}</span>
          </div>
        )}
        {sel && <Notes o={sel} />}

        {opts.length > 1 && (
          <button type="button" onClick={() => setOpen(!open)}
            className={cx('mt-2.5 flex items-center gap-1 text-[12.5px] font-semibold transition', decide ? 'text-amber-700 hover:text-amber-900' : 'text-[#1f4fbf] hover:text-[#0b2f6b]')}>
            <ChevronDown className={cx('h-4 w-4 transition-transform', open && 'rotate-180')} />
            {open ? 'Hide options' : `Compare ${opts.length} options`}
          </button>
        )}
      </div>

      {opts.length > 1 && open && (
        <div className="space-y-1.5 border-t border-slate-100 bg-slate-50/60 px-3 py-3">
          {opts.map((o, i) => (
            <AltRow key={`${o.product_id}-${i}`} o={o} rank={i + 1} selected={i === line.selected} current={sel}
              pending={pending === i} disabled={locked || pending !== null} undecided={decide} onClick={() => choose(i)} />
          ))}
        </div>
      )}
    </div>
  )
}

function Chip({ children, tone = 'slate', title }: { children: ReactNode; tone?: 'green' | 'amber' | 'slate' | 'blue' | 'muted'; title?: string }) {
  return (
    <span title={title} className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset',
      tone === 'green' && 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
      tone === 'amber' && 'bg-amber-50 text-amber-800 ring-amber-600/25',
      tone === 'blue' && 'bg-[#eef3fc] text-[#0b2f6b] ring-[#0b2f6b]/15',
      tone === 'slate' && 'bg-white text-slate-600 ring-slate-200',
      tone === 'muted' && 'bg-transparent text-slate-400 ring-slate-200')}>
      {children}
    </span>
  )
}

function DeliveryChip({ o }: { o: Option }) {
  const d = o.delivery
  if (!d?.date) return null
  if (d.on_time === false) {
    return <Chip tone="amber"><Clock className="h-3 w-3" />Arrives {day(d.date)} — late{!d.confirmed && <span className="font-normal opacity-75">· estimated</span>}</Chip>
  }
  return (
    <Chip tone={d.confirmed === false ? 'slate' : 'green'}>
      <Truck className="h-3 w-3" />{day(d.date)}{d.confirmed === false ? <span className="font-normal text-amber-700">· estimated</span> : <Check className="h-3 w-3" />}
    </Chip>
  )
}

function OptionChips({ o }: { o: Option }) {
  const tracked = isTracked(o)
  const allergens = cleanAllergens(o.allergens)
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      {o.usual && <Chip tone="green"><Star className="h-3 w-3" />Your usual</Chip>}
      {o.valio_substitute && <Chip tone="blue"><Repeat className="h-3 w-3" />Valio substitute</Chip>}
      {tracked
        ? <Chip tone="green" title={o.stock}><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />In stock</Chip>
        : <Chip tone="muted" title={o.stock}>Stock not tracked</Chip>}
      <DeliveryChip o={o} />
      {isNum(o.co2_kg) && <Chip><Leaf className="h-3 w-3 text-emerald-600" />{num(o.co2_kg)} kg CO₂</Chip>}
      {allergens.length > 0 && <span className="text-[11.5px] text-slate-400">Contains: {allergens.join(', ')}</span>}
    </div>
  )
}

function Notes({ o }: { o: Option }) {
  const notes = o.notes || []
  if (!notes.length) return null
  return (
    <div className="mt-1.5 space-y-0.5">
      {notes.map((n, i) => (
        <div key={i} className="flex items-start gap-1.5 text-[11.5px] leading-snug text-amber-700">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /><span className="line-clamp-2" title={n}>{n}</span>
        </div>
      ))}
    </div>
  )
}

function AltRow({ o, rank, selected, current, pending, disabled, undecided, onClick }: {
  o: Option; rank: number; selected: boolean; current?: Option; pending: boolean; disabled: boolean; undecided: boolean; onClick: () => void
}) {
  const diff = current && !selected ? o.total - current.total : 0
  return (
    <button type="button" onClick={onClick} disabled={disabled && !selected}
      className={cx('flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition',
        selected && !undecided ? 'bg-white shadow-sm ring-2 ring-[#1f4fbf]/60'
          : selected ? 'bg-white shadow-sm ring-2 ring-amber-300 hover:ring-[#1f4fbf]/60'
            : 'bg-white/60 ring-1 ring-slate-200 hover:bg-white hover:ring-[#1f4fbf]/30',
        disabled && !selected && 'cursor-not-allowed opacity-60')}>
      <div className={cx('mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-bold',
        selected && !undecided ? 'bg-[#0b2f6b] text-white' : selected ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-500 ring-1 ring-slate-200')}>
        {pending ? <Spinner className="h-2.5 w-2.5" /> : selected && !undecided ? <Check className="h-3 w-3" strokeWidth={3} /> : rank}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">Priority {rank}</span>
          {o.usual && <Chip tone="green"><Star className="h-3 w-3" />Your usual</Chip>}
          {o.valio_substitute && <Chip tone="blue">Valio substitute</Chip>}
        </div>
        <div className="mt-0.5 text-[13px] font-medium leading-snug text-slate-800">{o.name}</div>
        <div className="mt-0.5 text-[12px] text-slate-500">
          {qtyText(o)}{o.price_per ? ` · ${o.price_per}` : ''}
          {isNum(o.co2_kg) && <> · <Leaf className="inline h-3 w-3 -translate-y-px text-emerald-600" /> {num(o.co2_kg)} kg CO₂</>}
          {o.delivery?.date && <> · {o.delivery.on_time === false ? <span className="text-amber-700">late, {day(o.delivery.date)}</span> : day(o.delivery.date)}{o.delivery.confirmed === false && ' (est.)'}</>}
        </div>
        {o.why && <div className="mt-1 text-[12px] italic leading-snug text-slate-500">{o.why}</div>}
      </div>
      <div className="shrink-0 text-right">
        <div className="text-[13.5px] font-semibold tabular-nums text-slate-900">{eur(o.total)}</div>
        {!selected && current && (
          <div className={cx('text-[11.5px] font-medium tabular-nums', diff > 0.005 ? 'text-slate-500' : diff < -0.005 ? 'text-emerald-600' : 'text-slate-400')}>
            {eurDiff(diff)}
          </div>
        )}
        {selected && (undecided
          ? <div className="text-[11px] font-medium text-amber-700">recommended · tap to choose</div>
          : <div className="text-[11px] font-medium text-[#1f4fbf]">selected</div>)}
      </div>
    </button>
  )
}

// ------------------------------------------------------------------ footer + order status
function Footer({ cart, order, busy, locked, approver, onConfirm }: {
  cart: CartT; order: OrderInfo | null; busy: boolean; locked: boolean; approver?: string; onConfirm: () => Promise<void>
}) {
  const t = cart.totals || {}
  const total = isNum(t.total) ? t.total : cart.lines.reduce((s, l) => s + (l.options[l.selected]?.total || 0), 0)
  const open = t.choices_open || 0
  const [confirming, setConfirming] = useState(false)
  const disabled = busy || open > 0 || confirming || locked
  const title = open > 0 ? `Choose an option for ${open} line${open > 1 ? 's' : ''}` : undefined

  return (
    <div className="border-t border-slate-200 bg-white/90 px-7 py-4 shadow-[0_-8px_24px_-12px_rgba(15,23,42,0.12)] backdrop-blur">
      {order && <OrderStatus order={order} />}
      <div className="flex items-center gap-6">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Total excl. VAT</div>
          <div className="text-[26px] font-semibold leading-tight tabular-nums text-slate-900">{eur(total)}</div>
        </div>
        <div className="flex flex-col gap-1 text-[12.5px] text-slate-500">
          <span className="flex items-center gap-1.5"><Package className="h-3.5 w-3.5" />{t.lines ?? cart.lines.length} lines</span>
          {isNum(t.co2_kg) && <span className="flex items-center gap-1.5"><Leaf className="h-3.5 w-3.5 text-emerald-600" />{num(t.co2_kg)} kg CO₂e</span>}
        </div>
        {(open > 0 || (t.late || 0) > 0) && (
          <div className="flex flex-col gap-1 text-[12.5px] font-medium">
            {open > 0 && (
              <button type="button" onClick={() => {
                const l = cart.lines.find((x) => x.decision_needed)
                if (l) document.getElementById(`line-${l.key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }} className="flex items-center gap-1.5 text-amber-700 underline-offset-2 hover:underline">
                <Star className="h-3.5 w-3.5" />{open} choice{open > 1 ? 's' : ''} open
              </button>
            )}
            {(t.late || 0) > 0 && <span className="flex items-center gap-1.5 text-amber-700"><Clock className="h-3.5 w-3.5" />{t.late} late</span>}
          </div>
        )}
        <div className="ml-auto">
          {!order && (
            <span title={title} className="inline-block">
              <button type="button" disabled={disabled}
                onClick={async () => { setConfirming(true); await onConfirm(); setConfirming(false) }}
                className="flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-3 text-[14.5px] font-semibold text-white shadow-md shadow-emerald-600/20 transition hover:-translate-y-px hover:bg-emerald-700 disabled:translate-y-0 disabled:bg-slate-300 disabled:shadow-none">
                {confirming ? <Spinner className="h-4 w-4" /> : <CheckCircle2 className="h-4.5 w-4.5" />}
                Confirm order · {eur(total)}
              </button>
            </span>
          )}
        </div>
      </div>
      {!order && (
        <div className="mt-2 flex items-center gap-1.5 text-[11.5px] text-slate-400">
          <ShieldCheck className="h-3.5 w-3.5" />
          {open > 0 ? <span className="text-amber-700">{title} before confirming.</span>
            : <>Fixed prices, checked live. Valio verifies your purchasing mandate{approver ? `; ${approver}` : ''}.</>}
        </div>
      )}
    </div>
  )
}

function Accepted({ items }: { items: string[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2 pl-[42px] text-[11.5px] text-slate-500">
      <button type="button" onClick={() => setOpen(!open)} className="flex items-center gap-1 font-medium hover:text-slate-700">
        <ChevronDown className={cx('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
        You accepted {items.length} flagged item{items.length > 1 ? 's' : ''} (recorded in the audit trail)
      </button>
      {open && <ul className="mt-1 max-h-32 list-disc space-y-0.5 overflow-y-auto pl-5">{items.map((a, i) => <li key={i}>{a}</li>)}</ul>}
    </div>
  )
}

function OrderStatus({ order }: { order: OrderInfo }) {
  const s = (order.status || '').toUpperCase()
  const tone = s === 'CONFIRMED' ? 'green' : s === 'PENDING_APPROVAL' ? 'amber' : 'red'
  const reasons = order.reasons || []
  return (
    <div className={cx('anim-in mb-3.5 rounded-xl px-4 py-3 ring-1',
      tone === 'green' && 'bg-emerald-50 ring-emerald-200', tone === 'amber' && 'bg-amber-50 ring-amber-200', tone === 'red' && 'bg-red-50 ring-red-200')}>
      <div className="flex items-center gap-2.5">
        <div className={cx('grid h-8 w-8 shrink-0 place-items-center rounded-full text-white',
          tone === 'green' && 'bg-emerald-600', tone === 'amber' && 'bg-amber-500', tone === 'red' && 'bg-red-500')}>
          {tone === 'green' ? <Check className="h-4.5 w-4.5" strokeWidth={3} /> : tone === 'amber' ? <Clock className="h-4.5 w-4.5" /> : <X className="h-4.5 w-4.5" strokeWidth={3} />}
        </div>
        <div className="min-w-0 flex-1">
          <div className={cx('text-[14.5px] font-semibold', tone === 'green' && 'text-emerald-900', tone === 'amber' && 'text-amber-900', tone === 'red' && 'text-red-800')}>
            {tone === 'green' ? 'Confirmed · signed by Valio' : tone === 'amber' ? `Waiting for ${order.approver || 'your approver'}` : 'Valio could not accept this order'}
          </div>
          <div className="text-[12px] text-slate-600">
            <span className="font-mono">{order.order_id}</span>
            {order.delivery && <> · delivery {day(order.delivery)}</>}
            {isNum(order.total_with_tax) && <> · {eur(order.total_with_tax)} incl. VAT</>}
            {tone === 'green' && order.confirmed_by && <> · confirmed by {order.confirmed_by}</>}
          </div>
        </div>
        {tone === 'green' && order.signed && <ShieldCheck className="h-5 w-5 shrink-0 text-emerald-600" />}
      </div>
      {tone !== 'green' && reasons.length > 0 && (
        <ul className="mt-2 space-y-1 pl-[42px]">
          {reasons.map((r, i) => (
            <li key={i} className={cx('flex gap-1.5 text-[12.5px] leading-snug', tone === 'amber' ? 'text-amber-900' : 'text-red-800')}>
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-70" />{r}
            </li>
          ))}
        </ul>
      )}
      {order.note && <div className="mt-1.5 pl-[42px] text-[12.5px] italic text-slate-600">“{order.note}”</div>}
      {(order.accepted?.length || 0) > 0 && <Accepted items={order.accepted!} />}
    </div>
  )
}
