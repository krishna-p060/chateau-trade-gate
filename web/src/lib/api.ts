import { useEffect, useRef, useState } from 'react'
import type {
  AgentEvent, AgentRun, Approval, AuditEntry, Buyer, Integrity, Manifest, Order, Scenario, Stats,
} from '../types'

export class ApiError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Cannot reach the Trade Gate server.')
  }
  const text = await res.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }
  if (!res.ok) {
    const b = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>
    const detail = Array.isArray(b.detail) ? 'Invalid request.' : (b.detail as string | undefined)
    throw new ApiError(res.status, String(b.error ?? `HTTP_${res.status}`),
      String(b.message ?? detail ?? (typeof body === 'string' && body ? body : res.statusText)))
  }
  return body as T
}

const qs = (p: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams()
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  })
  const out = s.toString()
  return out ? `?${out}` : ''
}

export const api = {
  buyers: () => request<Buyer[]>('/api/console/buyers'),
  scenarios: () => request<Scenario[]>('/api/console/scenarios'),
  stats: () => request<Stats>('/api/console/stats'),
  orders: (buyer_id?: string) => request<Order[]>(`/api/console/orders${qs({ buyer_id })}`),
  approvals: (buyer_id?: string, status = 'PENDING') =>
    request<Approval[]>(`/api/console/approvals${qs({ buyer_id, status })}`),
  decide: (id: string, approver: string, approve: boolean, note: string) =>
    request<Order>(`/api/console/approvals/${encodeURIComponent(id)}`, {
      method: 'POST', body: JSON.stringify({ approver, approve, note }),
    }),
  audit: (p: { buyer_id?: string; ref?: string; since?: number } = {}) =>
    request<{ entries: AuditEntry[]; integrity: Integrity }>(`/api/console/audit${qs(p)}`),
  narrative: (p: { buyer_id?: string; ref?: string } = {}) =>
    request<{ text: string }>(`/api/console/audit/narrative${qs(p)}`),
  runAgent: (buyer_id: string, req: string, wait_for_approval_s = 600) =>
    request<{ run_id: string }>('/api/console/agent/run', {
      method: 'POST', body: JSON.stringify({ buyer_id, request: req, wait_for_approval_s }),
    }),
  run: (id: string) => request<AgentRun>(`/api/console/agent/runs/${encodeURIComponent(id)}`),
  manifest: () => request<Manifest>('/.well-known/trade-gate.json'),
  jwks: () => request<{ keys: Record<string, string>[] }>('/.well-known/jwks.json'),
}

/** The audit endpoint returns at most 500 entries per call (oldest first), so page through it. */
export async function fetchAllAudit(p: { buyer_id?: string; ref?: string; since?: number } = {}) {
  let since = p.since ?? 0
  const all: AuditEntry[] = []
  let integrity: Integrity = { valid: true }
  for (let i = 0; i < 40; i++) {
    const r = await api.audit({ ...p, since })
    integrity = r.integrity ?? integrity
    const entries = Array.isArray(r.entries) ? r.entries : []
    all.push(...entries)
    if (entries.length < 500) break
    since = entries[entries.length - 1].seq
  }
  return { entries: all, integrity }
}

export type StreamMessage = { type: 'audit'; entry: AuditEntry } | { type: 'agent'; event: AgentEvent }

/** Server-Sent Events from /api/console/stream with manual reconnect + backoff. */
export function useGateStream(onMessage: (m: StreamMessage) => void): boolean {
  const [connected, setConnected] = useState(false)
  const cb = useRef(onMessage)
  cb.current = onMessage

  useEffect(() => {
    let es: EventSource | null = null
    let retry = 1000
    let timer: number | undefined
    let stopped = false

    const connect = () => {
      if (stopped) return
      es = new EventSource('/api/console/stream')
      es.onopen = () => {
        retry = 1000
        setConnected(true)
      }
      es.onmessage = (ev) => {
        let data: unknown
        try {
          data = JSON.parse(ev.data)
        } catch {
          return
        }
        if (!data || typeof data !== 'object') return
        const d = data as Record<string, unknown>
        try {
          if (typeof d.seq === 'number') cb.current({ type: 'audit', entry: d as unknown as AuditEntry })
          else if (typeof d.kind === 'string' && typeof d.run_id === 'string')
            cb.current({ type: 'agent', event: d as unknown as AgentEvent })
        } catch (e) {
          console.error('stream handler failed', e)
        }
      }
      es.onerror = () => {
        setConnected(false)
        es?.close()
        timer = window.setTimeout(connect, retry)
        retry = Math.min(retry * 2, 10000)
      }
    }
    connect()
    return () => {
      stopped = true
      window.clearTimeout(timer)
      es?.close()
    }
  }, [])

  return connected
}

/** Run `fn` now and every `ms` while mounted. */
export function usePoll(fn: () => void | Promise<void>, ms: number, deps: unknown[] = []) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    let alive = true
    const tick = async () => {
      if (!alive) return
      try {
        await ref.current()
      } catch {
        /* polling is best-effort */
      }
    }
    tick()
    const id = window.setInterval(tick, ms)
    return () => {
      alive = false
      window.clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps])
}
