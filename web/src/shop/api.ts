import { useEffect, useRef, useState } from 'react'
import { request } from '../lib/api'
import type { Approval, AuditEntry, Integrity, Order } from '../types'
import type { Customer, Session } from './types'

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

const S = (sid: string) => `/api/shop/sessions/${encodeURIComponent(sid)}`

export interface Insights {
  signals: AuditEntry[]
  orders: Order[]
  integrity: Integrity & { ok?: boolean; entries?: number }
}

export interface SettingsIn {
  priorities: string[]
  avoid_allergens: string[]
  approval_limit_eur: number | null
  auto_confirm_standing_orders: boolean
}

export const shop = {
  customers: () => request<Customer[]>('/api/shop/customers'),
  create: (customer_id: string) => post<Session>('/api/shop/sessions', { customer_id }),
  session: (sid: string) => request<Session>(S(sid)),
  send: (sid: string, text: string) => post<Session>(`${S(sid)}/messages`, { text }),
  standingOrder: (sid: string, standing_order_id: string) => post<Session>(`${S(sid)}/standing-order`, { standing_order_id }),
  select: (sid: string, line_key: string, option: number) => post<Session>(`${S(sid)}/cart/select`, { line_key, option }),
  remove: (sid: string, line_key: string) => post<Session>(`${S(sid)}/cart/remove`, { line_key }),
  confirm: (sid: string) => post<Session>(`${S(sid)}/confirm`),
  saveSettings: (cid: string, body: SettingsIn) =>
    request<Customer>(`/api/shop/customers/${encodeURIComponent(cid)}/settings`, { method: 'PUT', body: JSON.stringify(body) }),
  insights: () => request<Insights>('/api/shop/insights'),
  approvals: () => request<Approval[]>('/api/console/approvals?status=PENDING'),
  decide: (id: string, approver: string, approve: boolean, note: string) =>
    post<Order>(`/api/console/approvals/${encodeURIComponent(id)}`, { approver, approve, note }),
}

/** Subscribe to a session's SSE stream; every message is a full Session snapshot. Reconnects with backoff. */
export function useSessionStream(sid: string | null, onSnapshot: (s: Session) => void): boolean {
  const [connected, setConnected] = useState(false)
  const cb = useRef(onSnapshot)
  useEffect(() => {
    cb.current = onSnapshot
  })

  useEffect(() => {
    if (!sid) return
    let es: EventSource | null = null
    let retry = 1000
    let timer: number | undefined
    let stopped = false
    const connect = () => {
      if (stopped) return
      es = new EventSource(`${S(sid)}/stream`)
      es.onopen = () => {
        retry = 1000
        setConnected(true)
      }
      es.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data)
          if (d && typeof d === 'object' && typeof d.id === 'string') cb.current(d as Session)
        } catch {
          /* ignore malformed frames */
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
      setConnected(false)
    }
  }, [sid])

  return connected
}
