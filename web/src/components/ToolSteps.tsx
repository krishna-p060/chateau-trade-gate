import {
  AlertTriangle, Ban, CalendarClock, ClipboardList, FileSignature, FileText, Gavel, Package, Search, ShieldCheck,
  ShoppingCart, Sparkles, Wrench,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { day, dayTime, eur, isNum, num, parseLoose, pct } from '../lib/format'
import type { TraceItem } from '../lib/trace'
import type { AuditEntry, Order } from '../types'
import { Badge, Collapsible, ReasonList, SignedBadge, StatusPill, TierBadge, cx } from './ui'

type ToolItem = Extract<TraceItem, { type: 'tool' }>

interface Ctx {
  names: Map<string, string>
  orders: Order[]
  chosenProducts: Set<string> // product ids the agent later quoted (to mark the chosen plan option)
  onOpenAudit: (ref: string) => void
}

const S = (v: unknown) => (typeof v === 'string' ? v : v == null ? '' : String(v))
const A = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const O = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {})

function rx(text: string | undefined, key: string): string | undefined {
  const m = new RegExp(`"${key}"\\s*:\\s*"([^"]*)"`).exec(text || '')
  return m?.[1]
}
function rxNum(text: string | undefined, key: string): number | undefined {
  const m = new RegExp(`"${key}"\\s*:\\s*(-?[\\d.]+)`).exec(text || '')
  return m ? Number(m[1]) : undefined
}

const toolMeta: Record<string, { icon: typeof Search; label: string }> = {
  get_my_mandate: { icon: FileSignature, label: 'Read its mandate' },
  search_products: { icon: Search, label: 'Catalog search' },
  get_product: { icon: Package, label: 'Product details' },
  check_offers: { icon: CalendarClock, label: 'Live price & availability' },
  get_offers: { icon: CalendarClock, label: 'Live price & availability' },
  plan_purchase: { icon: ClipboardList, label: 'Purchase plan' },
  create_quote: { icon: FileText, label: 'Signed quote' },
  place_order: { icon: ShoppingCart, label: 'Order placed' },
  get_order: { icon: Gavel, label: 'Order status' },
  get_audit_trail: { icon: ShieldCheck, label: 'Audit trail' },
}

export function ToolStep({ item, ctx }: { item: ToolItem; ctx: Ctx }) {
  const tool = item.call.tool || item.result?.tool || 'tool'
  const meta = toolMeta[tool] || { icon: Wrench, label: tool }
  const Icon = meta.icon
  const pending = !item.result
  const failed = item.result && item.result.ok === false
  const parsed = parseLoose(item.result?.preview)
  const errMsg = failed ? S(parsed?.message) || rx(item.result?.preview, 'message') || 'The tool returned an error.' : ''

  let body: ReactNode
  if (failed) body = <div className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700 ring-1 ring-red-100">{errMsg}</div>
  else if (tool === 'search_products') body = <SearchBody item={item} parsed={parsed} />
  else if (tool === 'plan_purchase') body = <PlanBody item={item} parsed={parsed} ctx={ctx} />
  else if (tool === 'create_quote') body = <QuoteBody item={item} parsed={parsed} ctx={ctx} />
  else if (tool === 'place_order') body = <OrderBody item={item} parsed={parsed} ctx={ctx} />
  else if (tool === 'get_my_mandate') body = <MandateBody item={item} />
  else if (tool === 'check_offers' || tool === 'get_offers') body = <OffersBody item={item} parsed={parsed} ctx={ctx} />
  else if (tool === 'get_order') body = <GetOrderBody item={item} parsed={parsed} />
  else if (tool === 'get_product') {
    const pid = S(item.call.input?.product_id)
    body = <div className="text-[13px] text-slate-600">{S(parsed?.name) || ctx.names.get(pid) || pid}</div>
  } else body = <Generic item={item} />

  return (
    <div className="min-w-0 flex-1">
      <div className="mb-1.5 flex items-center gap-2">
        <span className={cx('flex h-6 w-6 items-center justify-center rounded-md',
          failed ? 'bg-red-50 text-red-600' : 'bg-valio-50 text-valio-600')}>
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="text-[13px] font-semibold text-slate-900">{meta.label}</span>
        <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-500">{tool}</code>
        {pending && <span className="ml-1 inline-flex items-center gap-1 text-xs text-slate-400"><Spinner /> calling gate…</span>}
      </div>
      {!pending && body}
      {item.audits.length > 0 && <GateLog audits={item.audits} onOpenAudit={ctx.onOpenAudit} />}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx('inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-r-transparent', className)} />
}

function GateLog({ audits, onOpenAudit }: { audits: AuditEntry[]; onOpenAudit: (ref: string) => void }) {
  return (
    <div className="mt-2 space-y-1 border-l-2 border-valio-100 pl-3">
      {audits.map((a) => (
        <button type="button" key={a.seq} onClick={() => onOpenAudit(a.ref || '')}
          className="group flex w-full items-start gap-2 text-left text-[12px] leading-snug text-slate-500 hover:text-slate-800">
          <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-valio-500" />
          <span className="font-mono text-[11px] text-slate-400 group-hover:text-valio-600">#{a.seq}</span>
          <span className="min-w-0 flex-1">{a.summary}</span>
        </button>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ search
function SearchBody({ item, parsed }: { item: ToolItem; parsed: Record<string, unknown> | null }) {
  const inp = O(item.call.input)
  const count = isNum(parsed?.count) ? parsed.count : rxNum(item.result?.preview, 'count')
  const products = A(parsed?.products).map((p) => O(p))
  const listed = products.length
    ? products.map((p) => S(p.name)).filter(Boolean)
    : [...(item.result?.preview || '').matchAll(/"name"\s*:\s*"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1])
  const filters = [
    ...A(inp.diets).map((d) => S(d).replace('_', '-')),
    ...A(inp.avoid_allergens).map((a) => `no ${S(a)}`),
    ...A(inp.labels).map(S),
    inp.unit ? `unit: ${S(inp.unit)}` : '',
  ].filter(Boolean)
  return (
    <div className="space-y-2">
      <div className="text-[13px] text-slate-700">
        Searched <span className="font-semibold text-slate-900">“{S(inp.query)}”</span>
        {count !== undefined && <> → <span className="font-semibold">{count}</span> product{count === 1 ? '' : 's'}</>}
        {filters.length > 0 && <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">{filters.map((f) => <Badge key={f} tone="blue">{f}</Badge>)}</span>}
      </div>
      {listed.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {listed.slice(0, 6).map((n, i) => (
            <span key={i} className="max-w-[260px] truncate rounded-md bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200">{n}</span>
          ))}
          {(count ?? listed.length) > 6 && <span className="px-1 text-[11px] text-slate-400">+{(count ?? listed.length) - 6} more</span>}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ plan
interface PlanOption {
  tier: string
  lines: { product_id: string; name: string; units?: number; sales_unit?: string; unit_price?: number }[]
  total?: number
  confidence?: number
  delivery?: string
  meets?: boolean
  warnings: string[]
}

function PlanBody({ item, parsed, ctx }: { item: ToolItem; parsed: Record<string, unknown> | null; ctx: Ctx }) {
  const inp = O(item.call.input)
  const auditData = O(item.audits.find((a) => a.event === 'plan.created')?.data)
  let options: PlanOption[] = []
  if (parsed && Array.isArray(parsed.options)) {
    options = A(parsed.options).map((o0) => {
      const o = O(o0)
      return {
        tier: S(o.tier),
        lines: A(o.lines).map((l0) => {
          const l = O(l0)
          return { product_id: S(l.product_id), name: S(l.name) || ctx.names.get(S(l.product_id)) || S(l.product_id),
            units: l.units as number, sales_unit: S(l.sales_unit), unit_price: l.unit_price as number }
        }),
        total: o.total_price as number, confidence: o.confidence as number, delivery: S(o.earliest_delivery),
        meets: o.meets_deadline as boolean, warnings: A(o.warnings).map(S),
      }
    })
  } else if (Array.isArray(auditData.options)) {
    // preview was truncated: fall back to the (complete, compact) audit entry
    options = A(auditData.options).map((o0) => {
      const o = O(o0)
      // lines are [product_id, units] pairs, or objects if the gate records more detail
      const lines = A(o.lines).map((l0) => {
        const lo = O(l0)
        const l = Array.isArray(l0) ? l0 : [lo.product_id, lo.units]
        const pid = S(l[0])
        return { product_id: pid, name: S(lo.name) || ctx.names.get(pid) || `Product ${pid}`, units: l[1] as number,
          unit_price: isNum(lo.unit_price) ? lo.unit_price : undefined }
      })
      const total = (o.total ?? o.total_price) as number
      if (lines.length === 1 && lines[0].unit_price === undefined && isNum(total) && isNum(lines[0].units) && lines[0].units > 0)
        lines[0].unit_price = total / lines[0].units
      return { tier: S(o.tier), lines, total, confidence: o.confidence as number,
        delivery: S(o.earliest_delivery), meets: o.meets_deadline as boolean | undefined, warnings: [] }
    })
  }
  const rejected = (parsed && Array.isArray(parsed.rejected) && !Array.isArray(auditData.rejected) ? A(parsed.rejected) : A(auditData.rejected))
    .map((r) => O(r))
  const exception = S(parsed?.exception ?? auditData.exception)
  const unit = S(inp.unit) === 'l' ? 'L' : S(inp.unit) === 'unit' ? 'packs' : S(inp.unit)
  const need = `${num(inp.quantity)} ${unit} ${S(inp.query) || 'selected products'}`

  return (
    <div className="space-y-2">
      <div className="text-[13px] text-slate-700">
        Need: <span className="font-semibold text-slate-900">{need}</span>
        {inp.deliver_by ? <> by <span className="font-semibold text-slate-900">{day(inp.deliver_by)}</span></> : null}
        {A(inp.diets).length > 0 && <span className="ml-2 inline-flex gap-1 align-middle">{A(inp.diets).map((d) => <Badge key={S(d)} tone="blue">{S(d).replace('_', '-')}</Badge>)}</span>}
      </div>
      {options.length > 0 ? (
        <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
          <table className="w-full text-left text-[12.5px]">
            <thead className="whitespace-nowrap bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-2.5 py-1.5 font-semibold">Option</th>
                <th className="px-2.5 py-1.5 font-semibold">Product</th>
                <th className="px-2.5 py-1.5 text-right font-semibold">Qty × price</th>
                <th className="px-2.5 py-1.5 text-right font-semibold">Total</th>
                <th className="px-2.5 py-1.5 text-right font-semibold">Conf.</th>
                <th className="px-2.5 py-1.5 font-semibold">Delivery</th>
              </tr>
            </thead>
            <tbody>
              {options.slice(0, 6).map((o, i) => {
                const chosen = o.lines.length > 0 && o.lines.every((l) => ctx.chosenProducts.has(l.product_id))
                return (
                  <tr key={i} className={cx('border-t border-slate-100 align-top', chosen && 'bg-emerald-50/60')}>
                    <td className="px-2.5 py-1.5"><TierBadge tier={o.tier} /></td>
                    <td className="w-full max-w-0 px-2.5 py-1.5 text-slate-800">
                      {o.lines.map((l, j) => <div key={j} className="truncate" title={l.name}>{l.name}</div>)}
                      {chosen && <div className="mt-0.5 truncate text-[11px] font-semibold text-emerald-700">✓ chosen by the agent</div>}
                    </td>
                    <td className="whitespace-nowrap px-2.5 py-1.5 text-right tabular-nums text-slate-600">
                      {o.lines.map((l, j) => <div key={j}>{num(l.units)} × {eur(l.unit_price)}</div>)}
                    </td>
                    <td className="whitespace-nowrap px-2.5 py-1.5 text-right font-semibold tabular-nums text-slate-900">{eur(o.total)}</td>
                    <td className="px-2.5 py-1.5 text-right tabular-nums text-slate-600">{pct(o.confidence)}</td>
                    <td className={cx('whitespace-nowrap px-2.5 py-1.5', o.meets === false ? 'font-semibold text-amber-700' : 'text-slate-600')}>
                      {o.delivery ? day(o.delivery) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-[13px] text-slate-500">No option meets every requirement.</div>
      )}
      {exception && (
        <div className="flex gap-2 rounded-lg bg-amber-50 px-3 py-2 text-[13px] text-amber-900 ring-1 ring-amber-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" /> {exception}
        </div>
      )}
      {rejected.length > 0 && (
        <Collapsible title={<>Ruled out: {rejected.length} product{rejected.length === 1 ? '' : 's'}</>}>
          <ul className="max-h-56 space-y-1 overflow-y-auto rounded-lg bg-slate-50 p-2 ring-1 ring-slate-200">
            {rejected.map((r, i) => (
              <li key={i} className="flex gap-2 text-[12px] leading-snug">
                <Ban className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
                <span><span className="font-medium text-slate-700">{S(r.name) || S(r.product_id)}</span>
                  <span className="text-slate-500"> — {A(r.reasons).map(S).join(' ')}</span></span>
              </li>
            ))}
          </ul>
        </Collapsible>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ quote
function QuoteBody({ item, parsed, ctx }: { item: ToolItem; parsed: Record<string, unknown> | null; ctx: Ctx }) {
  const audit = item.audits[0]
  const preview = item.result?.preview
  if (audit?.event === 'quote.refused' || parsed?.error) {
    return (
      <div className="flex gap-2 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-800 ring-1 ring-red-100">
        <Ban className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        {audit?.summary || S(parsed?.message) || 'Quote refused.'}
      </div>
    )
  }
  const pq = O(parsed?.quote)
  const ad = O(audit?.data)
  const quoteId = S(pq.quote_id) || S(ad.quote_id) || rx(preview, 'quote_id') || ''
  const order = ctx.orders.find((o) => o.quote_id && o.quote_id === quoteId)
  const full = order?.quote
  const expires = S(pq.expires_at) || full?.expires_at || rx(preview, 'expires_at')
  const total = (pq.total_price as number) ?? (ad.total as number) ?? full?.total_price
  const linesSrc = full?.lines?.length ? full.lines : A(pq.lines).length ? A(pq.lines) : A(ad.lines)
  const inputLines = A(O(item.call.input).lines)
  const lines = (linesSrc.length ? linesSrc : inputLines).map((l0) => {
    const l = O(l0)
    const pid = S(l.product_id)
    return { pid, name: S(l.name) || ctx.names.get(pid) || `Product ${pid}`, units: l.units as number,
      sales_unit: S(l.sales_unit), price: l.unit_price as number, delivery: S(l.earliest_delivery),
      confirmed: l.earliest_delivery_confirmed as boolean | undefined, stock: S(l.stock_status) }
  })
  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2">
        <span className="font-mono text-[12px] font-semibold text-slate-700">{quoteId || 'quote'}</span>
        <SignedBadge />
        {expires && <span className="ml-auto text-[11px] text-slate-500">Price held until {dayTime(expires)}</span>}
      </div>
      <div className="divide-y divide-slate-100">
        {lines.map((l, i) => (
          <div key={i} className="flex items-center gap-3 px-3 py-1.5 text-[12.5px]">
            <span className="min-w-0 flex-1 truncate text-slate-800" title={l.name}>{l.name}</span>
            <span className="whitespace-nowrap tabular-nums text-slate-500">{num(l.units)} {l.sales_unit} × {eur(l.price)}</span>
            {l.delivery && (
              <span className={cx('whitespace-nowrap text-[11px]', l.confirmed === false ? 'text-amber-700' : 'text-slate-500')}>
                {day(l.delivery)}{l.confirmed === false ? ' (est.)' : ''}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between rounded-b-lg bg-slate-50 px-3 py-1.5 text-[12.5px]">
        <span className="text-slate-500">Total excl. VAT</span>
        <span className="font-bold tabular-nums text-slate-900">{eur(total)}</span>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ order
function OrderBody({ item, parsed, ctx }: { item: ToolItem; parsed: Record<string, unknown> | null; ctx: Ctx }) {
  const preview = item.result?.preview
  const req = item.audits.find((a) => a.event === 'order.requested')
  const orderId = S(parsed?.order_id) || rx(preview, 'order_id') || req?.ref || ''
  const order = ctx.orders.find((o) => o.id === orderId)
  const placedStatus = S(parsed?.status) || rx(preview, 'status') || order?.status || ''
  const nowStatus = order?.status || placedStatus
  const findings = order?.decision?.findings?.filter((f) => f.outcome !== 'AUTO').map((f) => S(f.message)) || []
  const reasons = findings.length ? findings : A(parsed?.reasons).map(S)
  const blocked = nowStatus === 'REJECTED'
  const total = order?.total ?? (parsed?.total_price as number) ?? rxNum(preview, 'total_price')
  const changed = placedStatus && nowStatus !== placedStatus
  const rationale = S(O(item.call.input).rationale)
  const approver = order?.approval?.approver

  return (
    <div className={cx('rounded-xl p-3 ring-1',
      nowStatus === 'CONFIRMED' ? 'bg-emerald-50/50 ring-emerald-200' : nowStatus === 'PENDING_APPROVAL' ? 'bg-amber-50/50 ring-amber-200' : blocked ? 'bg-red-50/50 ring-red-200' : 'bg-white ring-slate-200')}>
      <div className="flex flex-wrap items-center gap-3">
        <StatusPill status={nowStatus} order={order} size="lg" />
        <span className="text-lg font-bold tabular-nums text-slate-900">{eur(total)}</span>
        <button type="button" onClick={() => ctx.onOpenAudit(orderId)} className="font-mono text-[12px] text-slate-500 hover:text-valio-600 hover:underline">{orderId}</button>
        {order?.confirmation_jws && <SignedBadge label="Signed confirmation" />}
      </div>
      {changed && (
        <div className="mt-2 text-[12px] text-slate-600">
          Placed as <span className="font-semibold">{placedStatus.replace('_', ' ').toLowerCase()}</span>
          {approver ? <> · decided by <span className="font-semibold">{approver}</span></> : null}
          {order?.approval?.note ? <> · “{order.approval.note}”</> : null}
        </div>
      )}
      {rationale && <div className="mt-2 text-[12.5px] italic text-slate-600">Agent’s rationale: “{rationale}”</div>}
      {reasons.length > 0 && <div className="mt-2.5"><ReasonList reasons={reasons} tone={blocked && order?.decision?.outcome === 'BLOCKED' ? 'red' : 'amber'} /></div>}
      {nowStatus === 'PENDING_APPROVAL' && (
        <div className="mt-2.5 flex items-center gap-2 text-[12.5px] font-medium text-amber-800">
          <Sparkles className="h-4 w-4" /> Waiting for a human decision in the approval inbox →
        </div>
      )}
    </div>
  )
}

function GetOrderBody({ item, parsed }: { item: ToolItem; parsed: Record<string, unknown> | null }) {
  const status = S(parsed?.status) || rx(item.result?.preview, 'status')
  return (
    <div className="flex items-center gap-2 text-[13px] text-slate-600">
      <span className="font-mono text-[12px]">{S(item.call.input?.order_id)}</span>
      {status && <StatusPill status={status} />}
    </div>
  )
}

function MandateBody({ item }: { item: ToolItem }) {
  const p = item.result?.preview
  const auto = rxNum(p, 'auto_approve_max_order_eur')
  const weekly = rxNum(p, 'weekly_budget_eur')
  const avoid = /"avoid_allergens"\s*:\s*\[([^\]]*)\]/.exec(p || '')?.[1]?.replace(/"/g, '').split(',').map((s) => s.trim()).filter(Boolean) || []
  return (
    <div className="flex flex-wrap gap-1.5 text-[12px]">
      {auto !== undefined && <Badge tone="blue">auto-approve ≤ {eur(auto, true)}</Badge>}
      {weekly !== undefined && <Badge tone="blue">weekly budget {eur(weekly, true)}</Badge>}
      {avoid.length > 0 && <Badge tone="red">avoid: {avoid.join(', ')}</Badge>}
      {auto === undefined && <span className="text-slate-500">Spend limits, allergen rules and approvers loaded.</span>}
    </div>
  )
}

function OffersBody({ item, parsed, ctx }: { item: ToolItem; parsed: Record<string, unknown> | null; ctx: Ctx }) {
  const inp = O(item.call.input)
  const ids = A(inp.product_ids).map(S)
  const offers = A(parsed?.offers).map(O)
  return (
    <div className="space-y-1 text-[13px] text-slate-700">
      <div>Checked {ids.length} product{ids.length === 1 ? '' : 's'} for delivery by <span className="font-semibold">{day(inp.deliver_by)}</span>
        {inp.quantity ? <> ({num(inp.quantity)} {S(inp.unit)})</> : null}</div>
      {offers.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {offers.slice(0, 6).map((o, i) => (
            <span key={i} className="max-w-[260px] truncate rounded-md bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200">
              {S(o.name) || ctx.names.get(S(o.product_id))} {isNum(o.unit_price) ? `· ${eur(o.unit_price)}` : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function Generic({ item }: { item: ToolItem }) {
  return (
    <Collapsible title="Details">
      <pre className="max-h-48 overflow-auto rounded-lg bg-slate-50 p-2 font-mono text-[11px] text-slate-600 ring-1 ring-slate-200">
        {JSON.stringify(item.call.input ?? {}, null, 2)}
        {'\n→ '}
        {item.result?.preview}
      </pre>
    </Collapsible>
  )
}

