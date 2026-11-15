/** Keyless demo: /api/demo client, the status hook ShopApp reads, and the attack results kept across tab switches. */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { ApiError, request } from '../lib/api'
import type { Session } from './types'

export interface DemoStatus {
  demo: boolean
  llm: boolean
  note: string
}

export interface Attack {
  id: string
  title: string
  attempt: string
  known_gap?: boolean
}

export type Verdict = 'REFUSED' | 'BLOCKED' | 'HELD' | 'DETECTED' | 'NOT_STOPPED'

export interface AttackAuditRow {
  seq: number
  ts: string
  actor: string
  event: string
  summary: string
  hash: string
}

export interface AttackResult extends Attack {
  steps: string[]
  verdict: Verdict
  stopped: boolean
  code: string
  message: string
  audit: AttackAuditRow[]
  ms: number
}

export interface AttackRun {
  busy: boolean
  result?: AttackResult
  error?: { code: string; message: string }
}

export const demoApi = {
  status: () => request<DemoStatus>('/api/demo/status'),
  attacks: () => request<Attack[]>('/api/demo/attacks'),
  run: (id: string) => request<AttackResult>(`/api/demo/attacks/${encodeURIComponent(id)}`, { method: 'POST' }),
  recipe: (sid: string, recipe_id: string, portions: number) =>
    request<Session>(`/api/shop/sessions/${encodeURIComponent(sid)}/recipe`, { method: 'POST', body: JSON.stringify({ recipe_id, portions }) }),
}

const OPENED = 'aimo.breakit.opened'
let statusOnce: Promise<DemoStatus> | null = null

export function useDemoStatus(onKeyless: () => void): DemoStatus | null {
  const [status, setStatus] = useState<DemoStatus | null>(null)
  const cb = useRef(onKeyless)
  useEffect(() => {
    cb.current = onKeyless
  })
  useEffect(() => {
    let alive = true
    let timer: number | undefined
    const load = (n = 0) => {
      statusOnce ??= demoApi.status()
      statusOnce.then((s) => {
        if (!alive) return
        setStatus(s)
        if (!s.llm && !sessionStorage.getItem(OPENED)) {
          sessionStorage.setItem(OPENED, '1')
          cb.current()
        }
      }).catch(() => {
        statusOnce = null
        if (alive && n < 5) timer = window.setTimeout(() => load(n + 1), 2000)
      })
    }
    load()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [])
  return status
}

let runs: Record<string, AttackRun> = {}
const listeners = new Set<() => void>()
const put = (id: string, run: AttackRun) => {
  runs = { ...runs, [id]: run }
  listeners.forEach((f) => f())
}
const subscribe = (f: () => void) => {
  listeners.add(f)
  return () => {
    listeners.delete(f)
  }
}

export const useAttackRuns = () => useSyncExternalStore(subscribe, () => runs)

export async function runAttack(id: string): Promise<void> {
  if (runs[id]?.busy) return
  put(id, { result: runs[id]?.result, busy: true })
  try {
    put(id, { busy: false, result: await demoApi.run(id) })
  } catch (e) {
    const error = e instanceof ApiError ? { code: e.code, message: e.message } : { code: 'ERROR', message: String(e) }
    put(id, { result: runs[id]?.result, busy: false, error })
  }
}

let attacksCache: Attack[] | null = null
export const cachedAttacks = () => attacksCache
export async function loadAttacks(): Promise<Attack[]> {
  attacksCache = await demoApi.attacks()
  return attacksCache
}
