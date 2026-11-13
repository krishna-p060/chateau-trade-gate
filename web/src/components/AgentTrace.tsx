import {
  AlertOctagon, Bot, Brain, CheckCircle2, FileText, Hourglass, KeyRound, Search, ShieldCheck, User, UserCheck, XCircle,
} from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import { clock, day, eur } from '../lib/format'
import { buildTrace, runStage, runStatus, type RunState, type TraceItem } from '../lib/trace'
import type { AuditEntry, Buyer, Order } from '../types'
import { Spinner, ToolStep } from './ToolSteps'
import { Badge, Card, Collapsible, Markdown, StatusPill, cx } from './ui'

interface Props {
  run: RunState | null
  runs: RunState[]
  audit: AuditEntry[]
  orders: Order[]
  buyers: Buyer[]
  agentOffline: string | null
  onSelectRun: (id: string) => void
  onOpenAudit: (ref: string) => void
}

const STAGES = [
  { icon: Search, label: 'Search & plan' },
  { icon: FileText, label: 'Signed quote' },
  { icon: ShieldCheck, label: 'Guardrails' },
  { icon: UserCheck, label: 'Human approval' },
  { icon: KeyRound, label: 'Confirmed' },
]

export function AgentTrace({ run, runs, audit, orders, buyers, agentOffline, onSelectRun, onOpenAudit }: Props) {
  const trace = useMemo(() => (run ? buildTrace(run, audit) : null), [run, audit])
  const status = run ? runStatus(run) : ''
  const lastOrder = trace?.orderIds.length ? orders.find((o) => o.id === trace.orderIds[trace.orderIds.length - 1]) : undefined
  const stage = trace ? runStage(trace.items, lastOrder?.status) : -1
  const autoConfirmed = lastOrder?.status === 'CONFIRMED' && lastOrder.decision?.outcome === 'AUTO'
  const blocked = lastOrder?.status === 'REJECTED'
  const chosen = useMemo(() => {
    const s = new Set<string>()
    trace?.items.forEach((it) => {
      if (it.type === 'tool' && it.call.tool === 'create_quote' && it.result?.ok !== false) {
        const lines = (it.call.input?.lines as { product_id?: string }[] | undefined) || []
        lines.forEach((l) => l?.product_id && s.add(String(l.product_id)))
      }
    })
    return s
  }, [trace])

  // auto-scroll while the run grows, unless the user scrolled up to read
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const count = trace?.items.length ?? 0
  const lastLen = trace?.items.reduce((n, it) => n + ('result' in it && it.result ? 1 : 0) + it.key.length, 0) ?? 0
  useEffect(() => {
    const el = scroller.current
    if (el && stick.current) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [count, lastLen, orders])
  useEffect(() => { stick.current = true }, [run?.id])
  // only a user gesture can unstick (programmatic smooth scrolling passes through "not at bottom")
  const nearBottom = (el: HTMLElement) => el.scrollHeight - el.scrollTop - el.clientHeight < 80
  const userScrolled = () => window.setTimeout(() => {
    const el = scroller.current
    if (el) stick.current = nearBottom(el)
  }, 150)

  const buyer = buyers.find((b) => b.id === run?.buyer_id)
  const model = run?.events.find((e) => e.kind === 'agent.start')?.model

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* story strip */}
      <Card className="px-4 py-3">
        <div className="flex items-center gap-1">
          {STAGES.map((s, i) => {
            const Icon = s.icon
            let state: 'done' | 'active' | 'todo' | 'skip' | 'stop' = i < stage ? 'done' : i === stage ? (status === 'running' || i === 3 ? 'active' : 'done') : 'todo'
            if (i === 3 && autoConfirmed) state = 'skip'
            if (blocked && i >= 2) state = i === 2 ? 'stop' : 'todo'
            if (stage === 4 && !blocked && i === 4) state = 'done'
            return (
              <div key={s.label} className={cx('flex min-w-0 items-center gap-1', i < STAGES.length - 1 && 'flex-1')}>
                <div className={cx('flex flex-none items-center gap-1.5 rounded-lg px-2 py-1.5 transition-colors',
                  state === 'done' && 'bg-emerald-50 text-emerald-800',
                  state === 'active' && (i === 3 ? 'bg-amber-100 text-amber-900 ring-1 ring-amber-300' : 'bg-valio-600 text-white'),
                  state === 'todo' && 'text-slate-400',
                  state === 'skip' && 'text-slate-400 line-through decoration-slate-300',
                  state === 'stop' && 'bg-red-50 text-red-700 ring-1 ring-red-200')}>
                  <Icon className="hidden h-4 w-4 shrink-0 min-[1400px]:block" />
                  <span className="truncate whitespace-nowrap text-[12px] font-semibold">{i === 3 && autoConfirmed ? 'Not needed' : i === 2 && blocked ? 'Blocked' : s.label}</span>
                </div>
                {i < STAGES.length - 1 && <div className={cx('h-px min-w-2 flex-1', i < stage ? 'bg-emerald-300' : 'bg-slate-200')} />}
              </div>
            )
          })}
        </div>
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {/* header */}
        <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-[15px] font-bold text-slate-900">Live agent trace</h2>
              {run && (
                status === 'running' ? <Badge tone="blue"><Spinner className="h-2.5 w-2.5" /> running</Badge>
                  : status === 'error' ? <Badge tone="red">error</Badge>
                    : <Badge tone="green">finished</Badge>
              )}
              {model && <span className="font-mono text-[11px] text-slate-400">{model}</span>}
            </div>
            {run ? (
              <div className="mt-1 text-[13px] text-slate-600">
                <span className="font-semibold text-slate-800">{buyer?.name || run.buyer_id}</span>: “{run.request}”
              </div>
            ) : (
              <div className="mt-1 text-[13px] text-slate-500">The buyer’s AI agent talks to Valio only through the Trade Gate (MCP). Every step appears here as it happens.</div>
            )}
          </div>
          {runs.length > 1 && (
            <select value={run?.id || ''} onChange={(e) => onSelectRun(e.target.value)}
              className="max-w-[200px] rounded-lg border-0 bg-slate-50 py-1.5 pl-2 pr-7 text-[12px] text-slate-600 ring-1 ring-slate-200">
              {runs.map((r) => <option key={r.id} value={r.id}>{new Date(r.startedAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })} · {r.request.slice(0, 40)}</option>)}
            </select>
          )}
        </div>

        {agentOffline && (
          <div className="mx-5 mt-3 flex gap-3 rounded-lg bg-amber-50 px-4 py-3 text-[13px] text-amber-900 ring-1 ring-amber-200">
            <AlertOctagon className="h-5 w-5 shrink-0 text-amber-500" />
            <div>
              <div className="font-semibold">The buyer agent can’t start on this server</div>
              <div className="mt-0.5 text-amber-800">{agentOffline}</div>
              <div className="mt-1 text-amber-800/80">The gate itself is live: orders placed over MCP or REST still flow through guardrails, the approval inbox and the audit trail.</div>
            </div>
          </div>
        )}

        {/* timeline */}
        <div ref={scroller}
          onScroll={(e) => { if (nearBottom(e.currentTarget)) stick.current = true }}
          onWheel={userScrolled} onTouchMove={userScrolled} onKeyDown={userScrolled} onMouseDown={userScrolled}
          className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {!run || !trace ? (
            <EmptyTrace />
          ) : (
            <ol className="relative space-y-4">
              <div className="absolute bottom-2 left-[15px] top-2 w-px bg-slate-200" />
              {trace.items.map((it) => (
                <li key={it.key} className="anim-in relative flex gap-3">
                  <Item it={it} names={trace.names} orders={orders} chosen={chosen} onOpenAudit={onOpenAudit} />
                </li>
              ))}
              {status === 'running' && trace.items[trace.items.length - 1]?.type !== 'waiting' && (
                <li className="relative flex items-center gap-3 text-[13px] text-slate-400">
                  <span className="z-10 flex h-8 w-8 items-center justify-center rounded-full bg-white ring-1 ring-slate-200"><Spinner /></span>
                  Agent is working…
                </li>
              )}
            </ol>
          )}
        </div>
      </Card>
    </div>
  )
}

function Dot({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cx('z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ring-4 ring-white', className)}>{children}</span>
}

function Item({ it, names, orders, chosen, onOpenAudit }: {
  it: TraceItem; names: Map<string, string>; orders: Order[]; chosen: Set<string>; onOpenAudit: (ref: string) => void
}) {
  switch (it.type) {
    case 'start':
      return (
        <>
          <Dot className="bg-valio-600 text-white"><Bot className="h-4 w-4" /></Dot>
          <div className="pt-1.5 text-[13px] text-slate-600">
            <span className="font-semibold text-slate-800">Agent started</span> · connected to the gate over MCP with its signed mandate
            <span className="ml-2 font-mono text-[11px] text-slate-400">{clock(it.ev.ts)}</span>
          </div>
        </>
      )
    case 'thinking':
      return (
        <>
          <Dot className="bg-slate-100 text-slate-400"><Brain className="h-4 w-4" /></Dot>
          <div className="min-w-0 flex-1 pt-1.5">
            <Collapsible title={<span className="italic">Thinking: {firstLine(it.ev.text)}</span>}>
              <div className="whitespace-pre-wrap text-[12.5px] italic leading-relaxed text-slate-500">{it.ev.text}</div>
            </Collapsible>
          </div>
        </>
      )
    case 'say':
      return (
        <>
          <Dot className={it.final ? 'bg-emerald-600 text-white' : 'bg-valio-100 text-valio-700'}><Bot className="h-4 w-4" /></Dot>
          <div className={cx('min-w-0 flex-1 rounded-2xl rounded-tl-sm px-4 py-3 text-[13.5px] leading-relaxed text-slate-700',
            it.final ? 'bg-white shadow-sm ring-1 ring-emerald-200' : 'bg-slate-50 ring-1 ring-slate-200')}>
            {it.final && <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-emerald-700">Agent’s report to the buyer</div>}
            <Markdown text={it.ev.text} />
          </div>
        </>
      )
    case 'tool':
      return (
        <>
          <Dot className={cx('ring-1', it.result?.ok === false ? 'bg-red-50 text-red-600 ring-red-200' : 'bg-white text-valio-600 ring-slate-200')}>
            <span className="text-[10px] font-bold">MCP</span>
          </Dot>
          <ToolStep item={it} ctx={{ names, orders, chosenProducts: chosen, onOpenAudit }} />
        </>
      )
    case 'waiting':
      return (
        <>
          <Dot className="bg-amber-100 text-amber-700"><Hourglass className="h-4 w-4" /></Dot>
          <div className="pt-1.5 text-[13px] text-amber-800">
            <span className="font-semibold">Agent is waiting for the approver</span> · {(it.ev.orders || []).join(', ')}
          </div>
        </>
      )
    case 'error':
      return (
        <>
          <Dot className="bg-red-100 text-red-600"><XCircle className="h-4 w-4" /></Dot>
          <div className="min-w-0 flex-1 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-800 ring-1 ring-red-100">{it.ev.text || 'The agent stopped with an error.'}</div>
        </>
      )
    case 'human': {
      const d = it.audits[0]
      const approved = d.event === 'approval.approved'
      const confirmed = it.audits.find((a) => a.event === 'order.confirmed')
      const order = orders.find((o) => o.id === d.ref)
      return (
        <>
          <Dot className={approved ? 'bg-amber-500 text-white' : 'bg-red-500 text-white'}><User className="h-4 w-4" /></Dot>
          <div className={cx('min-w-0 flex-1 rounded-xl px-4 py-3 ring-1', approved ? 'bg-emerald-50 ring-emerald-200' : 'bg-red-50 ring-red-200')}>
            <div className="flex flex-wrap items-center gap-2">
              {approved ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <XCircle className="h-5 w-5 text-red-600" />}
              <span className="text-[14px] font-semibold text-slate-900">{d.actor.replace(/^human:/, '')} {approved ? 'approved' : 'rejected'} the order</span>
              {order && <StatusPill status={order.status} order={order} />}
              <span className="font-mono text-[11px] text-slate-400">{clock(d.ts)}</span>
            </div>
            {(d.data as { note?: string } | null)?.note && <div className="mt-1 text-[13px] italic text-slate-600">“{(d.data as { note?: string }).note}”</div>}
            {confirmed && (
              <div className="mt-1.5 text-[12.5px] text-slate-600">
                Gate issued a signed order confirmation · {eur(order?.total)} · delivery {day(order?.quote?.lines?.[0]?.earliest_delivery)}
              </div>
            )}
            <div className="mt-2 space-y-1 border-l-2 border-valio-100 pl-3">
              {it.audits.map((a) => (
                <button type="button" key={a.seq} onClick={() => onOpenAudit(a.ref || '')} className="flex gap-2 text-left text-[12px] text-slate-500 hover:text-slate-800">
                  <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-valio-500" />
                  <span className="font-mono text-[11px] text-slate-400">#{a.seq}</span> {a.summary}
                </button>
              ))}
            </div>
          </div>
        </>
      )
    }
  }
}

function firstLine(t?: string) {
  const s = (t || '').replace(/\s+/g, ' ').trim()
  return s.length > 110 ? s.slice(0, 110) + '…' : s
}

function EmptyTrace() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-valio-50 text-valio-600">
        <Bot className="h-7 w-7" />
      </div>
      <div className="text-[15px] font-semibold text-slate-800">No agent run yet</div>
      <div className="mt-1 max-w-md text-[13px] text-slate-500">
        Pick a scenario on the left, or type a request, and watch the buyer’s purchasing agent search, plan, get a signed
        quote and place an order. The gate decides: auto-confirm, send to a human, or block.
      </div>
    </div>
  )
}
