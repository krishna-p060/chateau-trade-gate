import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AgentTrace } from './components/AgentTrace'
import { ApprovalInbox } from './components/ApprovalInbox'
import { AuditTab } from './components/AuditTab'
import { BuyerPanel } from './components/BuyerPanel'
import { Header, type Tab } from './components/Header'
import { InterfaceTab } from './components/InterfaceTab'
import { Toasts, type ToastMsg } from './components/ui'
import { ApiError, api, fetchAllAudit, usePoll, useGateStream, type StreamMessage } from './lib/api'
import { eur } from './lib/format'
import { runStatus, type RunState } from './lib/trace'
import type { AgentEvent, AgentRun, Approval, AuditEntry, Buyer, Integrity, Order, Scenario, Stats } from './types'

const ORDER_EVENTS = new Set(['order.requested', 'policy.decision', 'approval.requested', 'approval.approved', 'approval.rejected', 'order.confirmed'])

export default function App() {
  const [tab, setTab] = useState<Tab>(() => (['live', 'audit', 'interface'].includes(location.hash.slice(1)) ? location.hash.slice(1) as Tab : 'live'))
  const [buyers, setBuyers] = useState<Buyer[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [buyerId, setBuyerId] = useState(() => localStorage.getItem('tg.buyer') || 'hotel-aurora')
  const [stats, setStats] = useState<Stats | null>(null)
  const [orders, setOrders] = useState<Order[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [integrity, setIntegrity] = useState<Integrity | null>(null)
  const [runs, setRuns] = useState<Record<string, RunState>>({})
  const [currentRun, setCurrentRun] = useState<string | null>(() => localStorage.getItem('tg.run'))
  const [starting, setStarting] = useState(false)
  const [agentOffline, setAgentOffline] = useState<string | null>(null)
  const [toasts, setToasts] = useState<ToastMsg[]>([])
  const [refFilter, setRefFilter] = useState('')
  const maxSeq = useRef(0)
  const runsRef = useRef(runs)
  runsRef.current = runs
  const currentRunRef = useRef(currentRun)
  currentRunRef.current = currentRun

  useEffect(() => { location.hash = tab }, [tab])
  useEffect(() => { localStorage.setItem('tg.buyer', buyerId) }, [buyerId])
  useEffect(() => { if (currentRun) localStorage.setItem('tg.run', currentRun) }, [currentRun])

  const toast = useCallback((t: Omit<ToastMsg, 'id'>, ms = 6000) => {
    const id = Date.now() + Math.random()
    setToasts((x) => [...x.slice(-3), { ...t, id }])
    window.setTimeout(() => setToasts((x) => x.filter((y) => y.id !== id)), ms)
  }, [])

  // ------------------------------------------------------------ data
  const addAudit = useCallback((entries: AuditEntry[]) => {
    if (!entries.length) return
    setAudit((prev) => {
      const map = new Map(prev.map((e) => [e.seq, e]))
      entries.forEach((e) => { if (e && typeof e.seq === 'number') map.set(e.seq, e) })
      const out = [...map.values()].sort((a, b) => a.seq - b.seq)
      maxSeq.current = out.length ? out[out.length - 1].seq : 0
      return out
    })
  }, [])

  const refreshCore = useCallback(async () => {
    const [s, o, a] = await Promise.allSettled([api.stats(), api.orders(), api.approvals()])
    if (s.status === 'fulfilled' && s.value) {
      setStats(s.value)
      if (s.value.audit) setIntegrity(s.value.audit)
    }
    if (o.status === 'fulfilled' && Array.isArray(o.value)) setOrders(o.value)
    if (a.status === 'fulfilled' && Array.isArray(a.value)) setApprovals(a.value)
  }, [])

  const refreshTimer = useRef<number | undefined>(undefined)
  const refreshSoon = useCallback(() => {
    window.clearTimeout(refreshTimer.current)
    refreshTimer.current = window.setTimeout(() => { refreshCore() }, 250)
  }, [refreshCore])

  // static-ish data, retried until it loads
  usePoll(async () => {
    if (!buyers.length) {
      const b = await api.buyers()
      if (Array.isArray(b) && b.length) {
        setBuyers(b)
        if (!b.some((x) => x.id === buyerId)) setBuyerId(b[0].id)
      }
    }
    if (!scenarios.length) {
      const s = await api.scenarios()
      if (Array.isArray(s)) setScenarios(s)
    }
  }, 5000, [buyers.length, scenarios.length])

  // fallback polling (SSE is the fast path)
  usePoll(refreshCore, 3000)
  usePoll(async () => {
    const r = maxSeq.current === 0 ? await fetchAllAudit() : await fetchAllAudit({ since: maxSeq.current })
    addAudit(r.entries)
    if (r.integrity) setIntegrity(r.integrity)
  }, 3000)

  // ------------------------------------------------------------ runs
  const upsertRunEvents = useCallback((runId: string, events: AgentEvent[], meta?: Partial<RunState>) => {
    setRuns((prev) => {
      const cur = prev[runId]
      const first = events[0]
      const base: RunState = cur || {
        id: runId,
        buyer_id: meta?.buyer_id || first?.buyer_id || '',
        request: meta?.request || first?.request || '',
        status: 'running',
        events: [],
        startSeq: meta?.startSeq ?? maxSeq.current,
        startedAt: Date.now(),
      }
      const merged = events.length >= base.events.length ? events : base.events
      const next: RunState = { ...base, ...meta, startSeq: base.startSeq, events: merged }
      if (!next.request) next.request = merged.find((e) => e.kind === 'agent.start')?.request || ''
      next.status = runStatus(next)
      return { ...prev, [runId]: next }
    })
  }, [])

  const onStream = useCallback((m: StreamMessage) => {
    if (m.type === 'audit') {
      addAudit([m.entry])
      if (ORDER_EVENTS.has(m.entry.event)) refreshSoon()
      if (m.entry.event === 'approval.requested') {
        toast({ tone: 'info', title: 'Approval requested', body: m.entry.summary })
      }
      setIntegrity((i) => (i && i.valid ? { ...i, checked: Math.max(i.checked || 0, m.entry.seq), head: m.entry.hash } : i))
    } else {
      const ev = m.event
      setRuns((prev) => {
        const cur = prev[ev.run_id]
        const base: RunState = cur || {
          id: ev.run_id, buyer_id: ev.buyer_id || '', request: ev.request || '', status: 'running', events: [],
          startSeq: typeof (ev as { _startSeq?: number })._startSeq === 'number' ? (ev as { _startSeq?: number })._startSeq! : maxSeq.current,
          startedAt: Date.now(),
        }
        const sig = JSON.stringify(ev)
        if (base.events.slice(-8).some((x) => JSON.stringify(x) === sig)) return prev // already have it (from polling)
        const next = { ...base, events: [...base.events, ev] }
        if (!next.request && ev.kind === 'agent.start') next.request = ev.request || ''
        next.status = runStatus(next)
        return { ...prev, [ev.run_id]: next }
      })
      if (ev.kind === 'agent.start') {
        // follow new runs (e.g. started from another window) unless one is still going here
        const cur = currentRunRef.current
        const follow = !cur || cur === ev.run_id || runsRef.current[cur]?.status !== 'running'
        if (follow) {
          setCurrentRun(ev.run_id)
          if (ev.buyer_id) setBuyerId(ev.buyer_id)
        }
      }
      if (ev.kind === 'agent.tool_result' && ev.tool === 'place_order') refreshSoon()
      if (ev.kind === 'agent.error') toast({ tone: 'error', title: 'Agent stopped', body: ev.text })
    }
  }, [addAudit, refreshSoon, toast])
  const connected = useGateStream(onStream)

  // poll the current run as a fallback for missed SSE events (and to restore it after a reload)
  const run = currentRun ? runs[currentRun] : undefined
  usePoll(async () => {
    if (!currentRun) return
    const r = runsRef.current[currentRun]
    if (r && r.status !== 'running') return
    try {
      const got: AgentRun = await api.run(currentRun)
      if (got && Array.isArray(got.events)) {
        upsertRunEvents(currentRun, got.events, {
          buyer_id: got.buyer_id, request: got.request,
          status: got.status,
          ...(r ? {} : { startSeq: 0 }),
        })
      }
    } catch (e) {
      // unknown to the server (e.g. it restarted) and nothing streamed locally: forget it
      if (e instanceof ApiError && e.status === 404 && !runsRef.current[currentRun]?.events.length) {
        setCurrentRun((c) => (c === currentRun ? null : c))
        localStorage.removeItem('tg.run')
      }
    }
  }, 2000, [currentRun])

  const startRun = async (bId: string, request: string) => {
    if (!request.trim()) return
    setStarting(true)
    setBuyerId(bId)
    const startSeq = maxSeq.current
    try {
      const { run_id } = await api.runAgent(bId, request)
      setAgentOffline(null)
      upsertRunEvents(run_id, [], { buyer_id: bId, request, startSeq, status: 'running' })
      setCurrentRun(run_id)
      setTab('live')
    } catch (e) {
      const err = e as ApiError
      if (err.code === 'NO_LLM_KEY') {
        setAgentOffline(err.message || 'No LLM API key is configured on the server.')
        toast({ tone: 'error', title: 'Buyer agent unavailable', body: err.message || 'No LLM key configured on the server.' }, 9000)
      } else {
        toast({ tone: 'error', title: 'Could not start the agent', body: err.message })
      }
    } finally {
      setStarting(false)
    }
  }

  const decide = async (a: Approval, approver: string, approve: boolean, note: string) => {
    try {
      const o = await api.decide(a.id, approver, approve, note)
      toast(approve
        ? { tone: 'success', title: `Approved: ${o?.status === 'CONFIRMED' ? 'order confirmed' : 'order updated'}`, body: `${o?.id || a.order_id} · ${eur(o?.total)} · signed confirmation issued` }
        : { tone: 'info', title: 'Order rejected', body: `${a.order_id} will not be placed. The agent has been told.` })
      window.setTimeout(refreshCore, 800)
      return true
    } catch (e) {
      const err = e as ApiError
      toast({ tone: 'error', title: 'Decision not recorded', body: err.message })
      refreshCore()
      return false
    }
  }

  const openAudit = (ref: string) => {
    setRefFilter(ref)
    setTab('audit')
  }

  const runList = useMemo(() => Object.values(runs).sort((a, b) => b.startedAt - a.startedAt), [runs])
  const pending = approvals.length

  return (
    <div className="flex h-full flex-col">
      <Header tab={tab} setTab={setTab} stats={stats} integrity={integrity} connected={connected} pending={pending} />
      <main className="mx-auto min-h-0 w-full max-w-[1680px] flex-1 px-5 py-4">
        {tab === 'live' && (
          <div className="grid h-full min-h-0 grid-cols-[272px_minmax(0,1fr)_340px] gap-4 min-[1400px]:grid-cols-[296px_minmax(0,1fr)_380px] min-[1400px]:gap-5">
            <BuyerPanel buyers={buyers} scenarios={scenarios} selected={buyerId} onSelect={setBuyerId}
              onRun={startRun} busy={starting || run?.status === 'running'} />
            <AgentTrace run={run || null} runs={runList} audit={audit} orders={orders} buyers={buyers}
              agentOffline={agentOffline} onSelectRun={setCurrentRun} onOpenAudit={openAudit} />
            <ApprovalInbox approvals={approvals} orders={orders} buyers={buyers} onDecide={decide} onOpenAudit={openAudit} />
          </div>
        )}
        {tab === 'audit' && <AuditTab audit={audit} buyers={buyers} refFilter={refFilter} setRefFilter={setRefFilter} />}
        {tab === 'interface' && <InterfaceTab />}
      </main>
      <Toasts toasts={toasts} dismiss={(id) => setToasts((x) => x.filter((y) => y.id !== id))} />
      {import.meta.env.DEV && <DevHooks onStream={onStream} />}
    </div>
  )
}

/** Dev-only: lets a test harness replay recorded stream messages (window.__tgReplay([...])). */
function DevHooks({ onStream }: { onStream: (m: StreamMessage) => void }) {
  useEffect(() => {
    const w = window as unknown as { __tgReplay?: (msgs: unknown[], delayMs?: number) => void }
    w.__tgReplay = (msgs, delayMs = 0) => {
      msgs.forEach((d, i) => {
        const fire = () => {
          const x = d as Record<string, unknown>
          if (typeof x.seq === 'number') onStream({ type: 'audit', entry: x as unknown as AuditEntry })
          else onStream({ type: 'agent', event: x as unknown as AgentEvent })
        }
        if (delayMs) window.setTimeout(fire, i * delayMs)
        else fire()
      })
    }
  }, [onStream])
  return null
}
