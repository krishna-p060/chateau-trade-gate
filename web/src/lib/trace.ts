import type { AgentEvent, AuditEntry } from '../types'
import { harvestNames } from './format'

/** A run as the dashboard tracks it (SSE events merged with polling of /agent/runs/{id}). */
export interface RunState {
  id: string
  buyer_id: string
  request: string
  status: string // running | done | error
  events: AgentEvent[]
  startSeq: number // audit head when the run started: only later entries can belong to it
  startedAt: number
}

export type TraceItem =
  | { type: 'start'; key: string; ev: AgentEvent }
  | { type: 'thinking'; key: string; ev: AgentEvent }
  | { type: 'say'; key: string; ev: AgentEvent; final: boolean }
  | { type: 'tool'; key: string; call: AgentEvent; result?: AgentEvent; audits: AuditEntry[] }
  | { type: 'waiting'; key: string; ev: AgentEvent }
  | { type: 'error'; key: string; ev: AgentEvent }
  | { type: 'human'; key: string; audits: AuditEntry[] }

const TOOL_EVENTS: Record<string, string[]> = {
  search_products: ['catalog.search'],
  check_offers: ['offers.check'],
  get_offers: ['offers.check'],
  plan_purchase: ['plan.created'],
  create_quote: ['quote.issued', 'quote.refused'],
  place_order: ['order.requested'],
}
const HUMAN_EVENTS = new Set(['approval.approved', 'approval.rejected'])

export function runStatus(run: RunState): string {
  if (run.events.some((e) => e.kind === 'agent.error')) return run.status === 'running' ? 'error' : run.status
  if (run.events.some((e) => e.kind === 'agent.done')) return 'done'
  return run.status
}

/**
 * Build the vertical timeline: agent events in order, with the gate's audit entries attached to the
 * tool call that caused them (matched by event type and order id), and human decisions inserted as
 * their own steps.
 */
export function buildTrace(run: RunState, audit: AuditEntry[]): { items: TraceItem[]; names: Map<string, string>; orderIds: string[] } {
  const names = new Map<string, string>()
  const startTs = run.events.find((e) => e.ts)?.ts || ''
  const candidates = audit
    .filter((a) => a.seq > run.startSeq && a.buyer_id === run.buyer_id && (!startTs || a.ts >= startTs))
    .sort((a, b) => a.seq - b.seq)
  const claimed = new Set<number>()
  const items: TraceItem[] = []
  const openCalls: Extract<TraceItem, { type: 'tool' }>[] = []
  const orderIds: string[] = []

  run.events.forEach((ev, i) => {
    const key = `${run.id}:${i}`
    switch (ev.kind) {
      case 'agent.start':
        items.push({ type: 'start', key, ev })
        break
      case 'agent.thinking':
        if (ev.text?.trim()) items.push({ type: 'thinking', key, ev })
        break
      case 'agent.say':
        if (ev.text?.trim()) items.push({ type: 'say', key, ev, final: false })
        break
      case 'agent.done': {
        const lastSay = [...items].reverse().find((x) => x.type === 'say') as Extract<TraceItem, { type: 'say' }> | undefined
        if (lastSay && (!ev.text || lastSay.ev.text?.trim() === ev.text.trim())) lastSay.final = true
        else if (ev.text?.trim()) items.push({ type: 'say', key, ev, final: true })
        break
      }
      case 'agent.tool_call': {
        const tool = ev.tool || 'tool'
        const step: Extract<TraceItem, { type: 'tool' }> = { type: 'tool', key, call: ev, audits: [] }
        const kinds = TOOL_EVENTS[tool]
        if (kinds) {
          const hit = candidates.find((a) => !claimed.has(a.seq) && kinds.includes(a.event))
          if (hit) {
            claimed.add(hit.seq)
            step.audits.push(hit)
            if (tool === 'place_order' && hit.ref) {
              orderIds.push(hit.ref)
              // the gate's own follow-ups for this order, up to the first human decision
              for (const a of candidates) {
                if (a.seq <= hit.seq || claimed.has(a.seq) || a.ref !== hit.ref) continue
                if (HUMAN_EVENTS.has(a.event)) break
                claimed.add(a.seq)
                step.audits.push(a)
              }
            }
          }
        }
        items.push(step)
        openCalls.push(step)
        break
      }
      case 'agent.tool_result': {
        harvestNames(ev.preview, names)
        const idx = openCalls.findIndex((c) => (c.call.tool || 'tool') === (ev.tool || 'tool') && !c.result)
        if (idx >= 0) {
          openCalls[idx].result = ev
          openCalls.splice(idx, 1)
        } else {
          items.push({ type: 'tool', key, call: { ...ev, kind: 'agent.tool_call', input: {} }, result: ev, audits: [] })
        }
        if (ev.tool === 'place_order') {
          const m = /"order_id"\s*:\s*"([^"]+)"/.exec(ev.preview || '')
          if (m && !orderIds.includes(m[1])) orderIds.push(m[1])
        }
        break
      }
      case 'agent.waiting':
        items.push({ type: 'waiting', key, ev })
        ;(ev.orders || []).forEach((o) => { if (!orderIds.includes(o)) orderIds.push(o) })
        break
      case 'agent.error':
        items.push({ type: 'error', key, ev })
        break
      default:
        break
    }
  })

  // Human decisions on this run's orders (plus the gate's confirmation that follows).
  for (const oid of orderIds) {
    const decision = candidates.find((a) => a.ref === oid && HUMAN_EVENTS.has(a.event) && !claimed.has(a.seq))
    if (!decision) continue
    claimed.add(decision.seq)
    const group = [decision]
    for (const a of candidates) {
      if (a.seq > decision.seq && a.ref === oid && !claimed.has(a.seq) && a.event === 'order.confirmed') {
        claimed.add(a.seq)
        group.push(a)
      }
    }
    const item: TraceItem = { type: 'human', key: `human:${decision.seq}`, audits: group }
    // place it before the first agent event that happened after the decision
    let at = items.length
    for (let i = 0; i < items.length; i++) {
      const it = items[i]
      const ts = 'ev' in it ? it.ev.ts : it.type === 'tool' ? it.call.ts : undefined
      const afterWaiting = items.slice(0, i).some((x) => x.type === 'waiting') || !items.some((x) => x.type === 'waiting')
      if (ts && ts > decision.ts && afterWaiting && it.type !== 'tool') {
        at = i
        break
      }
    }
    items.splice(at, 0, item)
  }

  // product names from audit data too (plan rejections)
  for (const it of items) {
    if (it.type !== 'tool') continue
    for (const a of it.audits) harvestNames(JSON.stringify(a.data ?? {}), names)
  }
  return { items, names, orderIds }
}

/** Which stage of the story the run has reached (for the progress strip). */
export function runStage(items: TraceItem[], orderStatus: string | undefined): number {
  let stage = items.length ? 0 : -1
  for (const it of items) {
    if (it.type !== 'tool') continue
    const t = it.call.tool
    if (t === 'search_products' || t === 'plan_purchase' || t === 'check_offers') stage = Math.max(stage, 0)
    if (t === 'create_quote') stage = Math.max(stage, 1)
    if (t === 'place_order') stage = Math.max(stage, 2)
  }
  if (orderStatus === 'PENDING_APPROVAL') stage = Math.max(stage, 3)
  if (orderStatus === 'CONFIRMED' || orderStatus === 'REJECTED') stage = 4
  return stage
}
