import { BarChart3, Check, ChevronDown, ClipboardCheck, MessageSquareText, SlidersHorizontal, Terminal } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Toasts, cx, type ToastMsg } from '../components/ui'
import { ApiError } from '../lib/api'
import type { Approval } from '../types'
import { shop, useSessionStream, type SettingsIn } from './api'
import { Approvals } from './Approvals'
import { Chat } from './Chat'
import { Preferences } from './Preferences'
import type { Customer, PlanItemOut, Session } from './types'
import { ValioView } from './ValioView'
import { Workspace } from './Workspace'
import { getLang, setLang as setLangGlobal, t, type Lang } from './i18n'
import { ShieldAlert } from 'lucide-react'
import { BreakIt, NoKeyNotice } from './BreakIt'
import { useDemoStatus } from './demo'

type Tab = 'assistant' | 'approvals' | 'valio' | 'preferences' | 'breakit'
const TABS: Tab[] = ['assistant', 'approvals', 'valio', 'preferences', 'breakit']
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
    const s = await shop.create(cid, getLang())
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
  const [lang, setLangState] = useState<Lang>(getLang)
  const sidRef = useRef<string | null>(null)

  const toast = useCallback((tone: ToastMsg['tone'], title: string, body?: string) => {
    const id = Date.now() + Math.random()
    setToasts((ts) => [...ts, { id, tone, title, body }])
    window.setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), tone === 'error' ? 7000 : 4500)
  }, [])
  const fail = useCallback((e: unknown, title?: string) => {
    toast('error', title || t('err_generic'), e instanceof Error ? e.message : String(e))
  }, [toast])

  useEffect(() => {
    window.history.replaceState(null, '', tab === 'assistant' ? location.pathname : `#${tab}`)
  }, [tab])
  useEffect(() => {
    const h = () => {
      const next = location.hash.slice(1) as Tab
      setTab(TABS.includes(next) ? next : 'assistant')
    }
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])
  const demo = useDemoStatus(() => setTab((x) => (x === 'assistant' ? 'breakit' : x)))

  // customers
  const reloadCustomers = useCallback(() => shop.customers(getLang()).then(setCustomers), [])
  useEffect(() => {
    let alive = true
    const load = (n = 0) => shop.customers(getLang()).then((c) => alive && setCustomers(c)).catch((e) => {
      if (n < 20) window.setTimeout(() => load(n + 1), 2000)
      else fail(e, t('err_customers'))
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
      else fail(e, t('err_start'))
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
      if (e instanceof ApiError && e.code === 'UNKNOWN_SESSION') {
        const s = await openSession(activeCid, true).catch(() => null)
        if (s) {
          sidRef.current = s.id
          setSession(s)
          toast('error', t('err_session_lost'), t('err_session_lost_body'))
          return false
        }
      }
      fail(e, title)
      return false
    }
  }
  const send = async (text: string) => {
    setSending(true)
    await run((sid) => shop.send(sid, text), t('err_send'))
    setSending(false)
  }
  const standing = async (id: string) => {
    setSending(true)
    await run((sid) => shop.standingOrder(sid, id), t('err_template_check'))
    setSending(false)
  }
  const select = async (key: string, i: number) => { await run((sid) => shop.select(sid, key, i), t('err_option')) }
  const remove = async (key: string) => { await run((sid) => shop.remove(sid, key), t('err_remove')) }
  const confirm = async () => {
    const ok = await run((sid) => shop.confirm(sid), t('err_order'))
    if (ok) loadApprovals()
  }
  const answers = async (a: Record<string, string>) => { await run((sid) => shop.answers(sid, a), t('err_answer')) }
  const approvePlan = async (items: PlanItemOut[], save: string[]) => {
    await run((sid) => shop.approvePlan(sid, items, save), t('err_approve_list'))
  }
  const setReference = async (r: string) => { await run((sid) => shop.reference(sid, r), t('err_reference')) }
  const notify = async (key: string) => { await run((sid) => shop.notify(sid, key), t('err_notify')) }
  const saveTemplate = async (name: string) => {
    const ok = await run((sid) => shop.saveTemplate(sid, name), t('err_template_save'))
    if (ok) reloadCustomers().catch(() => {})
  }
  const newConversation = async () => {
    try {
      const s = await openSession(activeCid, true)
      sidRef.current = s.id
      setSession(s)
    } catch (e) {
      fail(e, t('err_new'))
    }
  }
  const decide = async (a: Approval, approver: string, approve: boolean, note: string) => {
    try {
      await shop.decide(a.id, approver, approve, note)
      toast('success', approve ? t('toast_approved') : t('toast_rejected'),
        t(approve ? 'toast_approved_body' : 'toast_rejected_body', { id: a.order_id }))
      window.setTimeout(loadApprovals, 700)
      return true
    } catch (e) {
      fail(e, t('err_decision'))
      return false
    }
  }
  const saveSettings = async (body: SettingsIn) => {
    try {
      const c = await shop.saveSettings(activeCid, body, getLang())
      setCustomers((cs) => cs.map((x) => (x.id === c.id ? { ...x, ...c } : x)))
      toast('success', t('toast_prefs_saved'))
      return true
    } catch (e) {
      fail(e, t('err_save'))
      return false
    }
  }

  // language: UI strings switch at once; the open conversation and customer texts follow on the server
  const switchLang = async (l: Lang) => {
    if (l === lang) return
    setLangGlobal(l)
    setLangState(l)
    reloadCustomers().catch(() => {})
    const sid = sidRef.current
    if (sid) {
      try {
        applySession(await shop.setLang(sid, l))
      } catch (e) {
        fail(e, t('err_lang'))
      }
    }
  }

  // saved recipes and templates live on the customer: refetch when one is saved or Preferences opens
  const savedDishes = session?.plan?.dishes?.filter((d) => d.saved).length || 0
  useEffect(() => {
    if (savedDishes > 0 || tab === 'preferences') reloadCustomers().catch(() => {})
  }, [savedDishes, tab, reloadCustomers])

  return (
    <div className="flex h-full flex-col bg-[#f5f7fb] text-slate-800">
      <Header tab={tab} setTab={setTab} pending={approvals.length} customers={customers} customer={customer} onCustomer={setCid}
        lang={lang} onLang={switchLang} />
      <main className="min-h-0 flex-1">
        {tab === 'assistant' && (
          <div className="grid h-full grid-cols-[38fr_62fr]">
            <section className="flex min-h-0 flex-col border-r border-slate-200/80 bg-white">
              {demo?.llm === false && <NoKeyNotice onOpen={() => setTab('breakit')} />}
              <Chat session={session} sending={sending} onSend={send} onNew={newConversation} />
            </section>
            <section className="min-h-0 min-w-0 bg-[#f4f6fa]">
              <Workspace session={session} customer={customer} sending={sending} onSend={send} onStanding={standing}
                onAnswers={answers} onApprove={approvePlan} onNew={newConversation}
                onSelect={select} onRemove={remove} onConfirm={confirm}
                onReference={setReference} onSaveTemplate={saveTemplate} onNotify={notify} />
            </section>
          </div>
        )}
        {tab === 'approvals' && <div className="h-full overflow-y-auto"><Approvals approvals={approvals} customers={customers} onDecide={decide} /></div>}
        {tab === 'valio' && <div className="h-full overflow-y-auto"><ValioView customers={customers} /></div>}
        {tab === 'preferences' && customer && (
          <div className="h-full overflow-y-auto"><Preferences key={customer.id} customer={customer} onSave={saveSettings} /></div>
        )}
        {tab === 'breakit' && <div className="h-full overflow-y-auto"><BreakIt status={demo} /></div>}
      </main>
      <Toasts toasts={toasts} dismiss={(id) => setToasts((ts) => ts.filter((x) => x.id !== id))} />
    </div>
  )
}

// ------------------------------------------------------------------ header
function Header({ tab, setTab, pending, customers, customer, onCustomer, lang, onLang }: {
  tab: Tab; setTab: (t: Tab) => void; pending: number
  customers: Customer[]; customer: Customer | null; onCustomer: (id: string) => void
  lang: Lang; onLang: (l: Lang) => void
}) {
  const items: { id: Tab; label: string; icon: typeof BarChart3 }[] = [
    { id: 'assistant', label: t('tab_assistant'), icon: MessageSquareText },
    { id: 'approvals', label: t('tab_approvals'), icon: ClipboardCheck },
    { id: 'valio', label: t('tab_valio'), icon: BarChart3 },
    { id: 'preferences', label: t('tab_prefs'), icon: SlidersHorizontal },
    { id: 'breakit', label: t('tab_break'), icon: ShieldAlert },
  ]
  return (
    <header className="relative z-20 flex h-14 shrink-0 items-center gap-4 whitespace-nowrap border-b border-slate-200 bg-white px-6">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-[#0b2f6b] text-[15px] font-bold tracking-tight text-white shadow-sm">VA</div>
        <div className="leading-tight">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#0b2f6b]/70">{t('brand')}</div>
          <div className="flex items-center gap-2 whitespace-nowrap text-[16px] font-semibold text-slate-900">
            {t('app')}
            <span className="rounded-md bg-amber-100 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-amber-800">{t('prototype')}</span>
          </div>
        </div>
      </div>

      <nav className="ml-2 flex items-center gap-0.5">
        {items.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => setTab(id)}
            className={cx('relative flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-[13.5px] font-medium transition',
              tab === id ? 'bg-[#eef3fc] text-[#0b2f6b]' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800')}>
            <Icon className="h-4 w-4" />
            {label}
            {id === 'approvals' && pending > 0 && (
              <span className="grid h-5 min-w-5 place-items-center rounded-full bg-amber-500 px-1.5 text-[11px] font-bold text-white">{pending}</span>
            )}
          </button>
        ))}
      </nav>

      <div className="ml-auto flex min-w-0 items-center gap-3">
        <div role="group" aria-label={t('language')} className="flex rounded-lg bg-slate-100 p-0.5 text-[12px] font-semibold">
          {(['en', 'fi'] as Lang[]).map((l) => (
            <button key={l} type="button" onClick={() => onLang(l)} aria-pressed={lang === l}
              className={cx('rounded-md px-2 py-1 uppercase transition', lang === l ? 'bg-white text-[#0b2f6b] shadow-sm' : 'text-slate-500 hover:text-slate-800')}>
              {l}
            </button>
          ))}
        </div>
        <CustomerSwitcher customers={customers} customer={customer} onChange={onCustomer} />
        <a href="/console" title={t('dev_console')} className="flex items-center gap-1 text-[12px] text-slate-400 transition hover:text-[#0b2f6b]">
          <Terminal className="h-3.5 w-3.5" /> <span className="hidden 2xl:inline">{t('dev_console')}</span>
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
        className="flex min-w-0 max-w-[230px] items-center gap-2.5 rounded-xl py-1.5 pl-1.5 pr-2.5 text-left ring-1 ring-slate-200 transition hover:bg-slate-50">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-600 text-[12px] font-bold text-white">
          {customer ? initials(customer.contact?.name || customer.name) : '…'}
        </div>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[13px] font-semibold text-slate-800">{customer?.name || t('loading')}</div>
          <div className="truncate text-[11.5px] text-slate-500">{customer?.contact ? `${customer.contact.name} · ${customer.contact.role}` : ''}</div>
        </div>
        <ChevronDown className={cx('h-4 w-4 text-slate-400 transition', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="anim-in absolute right-0 top-full mt-2 w-80 overflow-hidden rounded-xl bg-white p-1.5 shadow-xl ring-1 ring-slate-200">
          <div className="px-2.5 pb-1 pt-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">{t('signed_in_as')}</div>
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
