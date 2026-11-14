import { BarChart3, Check, ChevronDown, ClipboardCheck, MessageSquareText, SlidersHorizontal, Terminal } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Toasts, cx, type ToastMsg } from '../components/ui'
import { ApiError } from '../lib/api'
import { eur } from '../lib/format'
import type { Approval } from '../types'
import { shop, useSessionStream, type SettingsIn } from './api'
import { Approvals } from './Approvals'
import { Cart } from './Cart'
import { Chat } from './Chat'
import { splitPerson } from './format'
import { Preferences } from './Preferences'
import type { Customer, Session } from './types'
import { ValioView } from './ValioView'

type Tab = 'assistant' | 'approvals' | 'valio' | 'preferences'
const TABS: Tab[] = ['assistant', 'approvals', 'valio', 'preferences']
const sidKey = (cid: string) => `aimo.sid.${cid}`

// one in-flight session lookup per customer (StrictMode mounts effects twice)
const inflight = new Map<string, Promise<Session>>()
function openSession(cid: string, fresh = false): Promise<Session> {
  const k = `${cid}:${fresh}`
  const existing = inflight.get(k)
  if (existing) return existing
  const p = (async () => {
    const sid = fresh ? null : localStorage.getItem(sidKey(cid))
    if (sid) {
      try {
        return await shop.session(sid)
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 404) throw e
      }
    }
    const s = await shop.create(cid)
    localStorage.setItem(sidKey(cid), s.id)
    return s
  })().finally(() => inflight.delete(k))
  inflight.set(k, p)
  return p
}

export default function ShopApp() {
  const [tab, setTab] = useState<Tab>(() => (TABS.includes(location.hash.slice(1) as Tab) ? location.hash.slice(1) as Tab : 'assistant'))
  const [customers, setCustomers] = useState<Customer[]>([])
  const [cid, setCid] = useState(() => localStorage.getItem('aimo.customer') || 'kultakeittio-catering')
  const [rawSession, setSession] = useState<Session | null>(null)
  const [sending, setSending] = useState(false)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [toasts, setToasts] = useState<ToastMsg[]>([])
  const sidRef = useRef<string | null>(null)

  const toast = useCallback((tone: ToastMsg['tone'], title: string, body?: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, tone, title, body }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 7000 : 4500)
  }, [])
  const fail = useCallback((e: unknown, title = 'Something went wrong') => {
    toast('error', title, e instanceof Error ? e.message : String(e))
  }, [toast])

  useEffect(() => {
    window.history.replaceState(null, '', tab === 'assistant' ? location.pathname : `#${tab}`)
  }, [tab])
  useEffect(() => {
    const h = () => {
      const t = location.hash.slice(1) as Tab
      setTab(TABS.includes(t) ? t : 'assistant')
    }
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])

  // customers
  const reloadCustomers = useCallback(() => shop.customers().then(setCustomers), [])
  useEffect(() => {
    let alive = true
    const load = (n = 0) => shop.customers().then((c) => alive && setCustomers(c)).catch((e) => {
      if (n < 20) window.setTimeout(() => load(n + 1), 2000)
      else fail(e, 'Could not load customers')
    })
    load()
    return () => { alive = false }
  }, [fail])

  // fall back to the first customer if the remembered one no longer exists
  const activeCid = customers.length && !customers.some((c) => c.id === cid) ? customers[0].id : cid
  const customer = customers.find((c) => c.id === activeCid) || null

  // session per customer
  const applySession = useCallback((s: Session) => {
    if (s.id === sidRef.current) setSession(s)
  }, [])
  const session = rawSession && rawSession.customer_id === activeCid ? rawSession : null
  useEffect(() => {
    let alive = true
    localStorage.setItem('aimo.customer', activeCid)
    sidRef.current = null
    const go = (n = 0) => openSession(activeCid).then((s) => {
      if (!alive) return
      sidRef.current = s.id
      setSession(s)
    }).catch((e) => {
      if (!alive) return
      if (n < 20) window.setTimeout(() => go(n + 1), 2000)
      else fail(e, 'Could not start the assistant')
    })
    go()
    return () => { alive = false }
  }, [activeCid, fail])
  useSessionStream(session?.id ?? null, applySession)

  // approvals (badge + tab)
  const loadApprovals = useCallback(() => shop.approvals().then(setApprovals).catch(() => {}), [])
  useEffect(() => {
    loadApprovals()
    const id = window.setInterval(loadApprovals, 5000)
    return () => window.clearInterval(id)
  }, [loadApprovals])

  // ---------------------------------------------------------------- actions
  const run = async (fn: (sid: string) => Promise<Session>, title?: string) => {
    const sid = sidRef.current
    if (!sid) return false
    try {
      applySession(await fn(sid))
      return true
    } catch (e) {
      fail(e, title)
      return false
    }
  }
  const send = async (text: string) => {
    setSending(true)
    await run((sid) => shop.send(sid, text), 'Could not send')
    setSending(false)
  }
  const standing = async (id: string) => {
    setSending(true)
    await run((sid) => shop.standingOrder(sid, id), 'Could not check the order template')
    setSending(false)
  }
  const select = async (key: string, i: number) => { await run((sid) => shop.select(sid, key, i), 'Could not change the option') }
  const remove = async (key: string) => { await run((sid) => shop.remove(sid, key), 'Could not remove the line') }
  const confirm = async () => {
    const ok = await run((sid) => shop.confirm(sid), 'Order not placed')
    if (ok) loadApprovals()
  }
  const setReference = async (r: string) => { await run((sid) => shop.reference(sid, r), 'Could not save your reference') }
  const notify = async (key: string) => { await run((sid) => shop.notify(sid, key), 'Could not set the notification') }
  const saveTemplate = async (name: string) => {
    const ok = await run((sid) => shop.saveTemplate(sid, name), 'Could not save the order template')
    if (ok) reloadCustomers().catch(() => {})
  }
  const newConversation = async () => {
    try {
      const s = await openSession(activeCid, true)
      sidRef.current = s.id
      setSession(s)
    } catch (e) {
      fail(e, 'Could not start a new conversation')
    }
  }
  const decide = async (a: Approval, approver: string, approve: boolean, note: string) => {
    try {
      await shop.decide(a.id, approver, approve, note)
      toast('success', approve ? 'Order approved' : 'Order rejected',
        approve ? `${a.order_id} is confirmed and signed by Valio.` : `${a.order_id} will not be delivered.`)
      window.setTimeout(loadApprovals, 700)
      return true
    } catch (e) {
      fail(e, 'Decision failed')
      return false
    }
  }
  const saveSettings = async (body: SettingsIn) => {
    try {
      const c = await shop.saveSettings(activeCid, body)
      setCustomers((cs) => cs.map((x) => (x.id === c.id ? { ...x, ...c } : x)))
      toast('success', 'Saved — your purchasing mandate was re-signed ✓')
      return true
    } catch (e) {
      fail(e, 'Could not save')
      return false
    }
  }

  const approverHint = customer?.approvers?.[0] && customer.approval_limit_eur != null
    ? `orders above ${eur(customer.approval_limit_eur, true)} go to ${splitPerson(customer.approvers[0]).name}` : undefined

  return (
    <div className="flex h-full flex-col bg-[#f5f7fb] text-slate-800">
      <Header tab={tab} setTab={setTab} pending={approvals.length} customers={customers} customer={customer} onCustomer={setCid} />
      <main className="min-h-0 flex-1">
        {tab === 'assistant' && (
          <div className="grid h-full grid-cols-[42fr_58fr]">
            <section className="min-h-0 border-r border-slate-200/80 bg-[#f8fafd]">
              <Chat session={session} customer={customer} sending={sending} onSend={send} onStanding={standing} onNew={newConversation} />
            </section>
            <section className="min-h-0 bg-[#f1f4f9]">
              <Cart session={session} approver={approverHint} onSelect={select} onRemove={remove} onConfirm={confirm}
                onReference={setReference} onSaveTemplate={saveTemplate} onNotify={notify} />
            </section>
          </div>
        )}
        {tab === 'approvals' && <div className="h-full overflow-y-auto"><Approvals approvals={approvals} customers={customers} onDecide={decide} /></div>}
        {tab === 'valio' && <div className="h-full overflow-y-auto"><ValioView customers={customers} /></div>}
        {tab === 'preferences' && customer && (
          <div className="h-full overflow-y-auto"><Preferences key={customer.id} customer={customer} onSave={saveSettings} /></div>
        )}
      </main>
      <Toasts toasts={toasts} dismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  )
}

// ------------------------------------------------------------------ header
function Header({ tab, setTab, pending, customers, customer, onCustomer }: {
  tab: Tab; setTab: (t: Tab) => void; pending: number
  customers: Customer[]; customer: Customer | null; onCustomer: (id: string) => void
}) {
  const items: { id: Tab; label: string; icon: typeof BarChart3 }[] = [
    { id: 'assistant', label: 'Assistant', icon: MessageSquareText },
    { id: 'approvals', label: 'Approvals', icon: ClipboardCheck },
    { id: 'valio', label: 'Valio view', icon: BarChart3 },
    { id: 'preferences', label: 'Preferences', icon: SlidersHorizontal },
  ]
  return (
    <header className="relative z-20 flex h-16 shrink-0 items-center gap-6 border-b border-slate-200 bg-white px-6">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-[#0b2f6b] text-[15px] font-bold tracking-tight text-white shadow-sm">VA</div>
        <div className="leading-tight">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#0b2f6b]/70">Valio Aimo</div>
          <div className="flex items-center gap-2 text-[16px] font-semibold text-slate-900">
            Aimo Assistant
            <span className="rounded-md bg-amber-100 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-amber-800">prototype</span>
          </div>
        </div>
      </div>

      <nav className="ml-4 flex items-center gap-1">
        {items.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => setTab(id)}
            className={cx('relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-[13.5px] font-medium transition',
              tab === id ? 'bg-[#eef3fc] text-[#0b2f6b]' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800')}>
            <Icon className="h-4 w-4" />
            {label}
            {id === 'approvals' && pending > 0 && (
              <span className="grid h-5 min-w-5 place-items-center rounded-full bg-amber-500 px-1.5 text-[11px] font-bold text-white">{pending}</span>
            )}
          </button>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-4">
        <CustomerSwitcher customers={customers} customer={customer} onChange={onCustomer} />
        <a href="/console" className="flex items-center gap-1 text-[12px] text-slate-400 transition hover:text-[#0b2f6b]">
          <Terminal className="h-3.5 w-3.5" /> Developer console
        </a>
      </div>
    </header>
  )
}

function initials(name: string) {
  return name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
}

function CustomerSwitcher({ customers, customer, onChange }: { customers: Customer[]; customer: Customer | null; onChange: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(!open)}
        className="flex items-center gap-2.5 rounded-xl py-1.5 pl-1.5 pr-2.5 text-left ring-1 ring-slate-200 transition hover:bg-slate-50">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-600 text-[12px] font-bold text-white">
          {customer ? initials(customer.contact?.name || customer.name) : '…'}
        </div>
        <div className="leading-tight">
          <div className="text-[13px] font-semibold text-slate-800">{customer?.name || 'Loading…'}</div>
          <div className="text-[11.5px] text-slate-500">{customer?.contact ? `${customer.contact.name} · ${customer.contact.role}` : ''}</div>
        </div>
        <ChevronDown className={cx('h-4 w-4 text-slate-400 transition', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="anim-in absolute right-0 top-full mt-2 w-80 overflow-hidden rounded-xl bg-white p-1.5 shadow-xl ring-1 ring-slate-200">
          <div className="px-2.5 pb-1 pt-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">Signed in as</div>
          {customers.map((c) => (
            <button key={c.id} type="button" onClick={() => { onChange(c.id); setOpen(false) }}
              className={cx('flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition hover:bg-slate-50', c.id === customer?.id && 'bg-[#eef3fc]')}>
              <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-[12px] font-bold text-slate-600">{initials(c.contact?.name || c.name)}</div>
              <div className="min-w-0 flex-1 leading-tight">
                <div className="truncate text-[13px] font-semibold text-slate-800">{c.name}</div>
                <div className="truncate text-[11.5px] text-slate-500">{c.contact?.name} · {c.contact?.role}</div>
              </div>
              {c.id === customer?.id && <Check className="h-4 w-4 text-[#0b2f6b]" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
