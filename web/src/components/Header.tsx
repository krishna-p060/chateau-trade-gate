import { Activity, Link2, ShieldAlert, ShieldCheck } from 'lucide-react'
import { num, short } from '../lib/format'
import type { Integrity, Stats } from '../types'
import { cx } from './ui'

export type Tab = 'live' | 'audit' | 'interface'

const TABS: { id: Tab; label: string }[] = [
  { id: 'live', label: 'Live view' },
  { id: 'audit', label: 'Audit trail' },
  { id: 'interface', label: 'Open interface' },
]

export function Header({ tab, setTab, stats, integrity, connected, pending }: {
  tab: Tab; setTab: (t: Tab) => void; stats: Stats | null; integrity: Integrity | null; connected: boolean; pending: number
}) {
  const o = stats?.orders || {}
  const chain = integrity || stats?.audit || null
  return (
    <header className="bg-valio-600 text-white shadow-md">
      <div className="mx-auto flex h-16 max-w-[1680px] items-center gap-4 px-5 whitespace-nowrap min-[1400px]:gap-6">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white text-valio-600 shadow-sm">
            <svg viewBox="0 0 32 32" className="h-6 w-6"><path d="M8 10h16M8 16h16M8 22h9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" fill="none" /><circle cx="23" cy="22" r="3.2" fill="#22c55e" /></svg>
          </div>
          <div className="leading-tight">
            <div className="text-[17px] font-bold tracking-tight">Valio Aimo Trade Gate</div>
            <div className="text-[11.5px] text-valio-100">open interface for purchasing agents</div>
          </div>
        </div>

        <nav className="flex items-center gap-1 rounded-xl bg-valio-800/40 p-1">
          {TABS.map((t) => (
            <button type="button" key={t.id} onClick={() => setTab(t.id)}
              className={cx('relative rounded-lg px-3 py-1.5 text-[13px] font-semibold transition min-[1400px]:px-3.5',
                tab === t.id ? 'bg-white text-valio-700 shadow-sm' : 'text-valio-100 hover:bg-white/10 hover:text-white')}>
              {t.label}
              {t.id === 'live' && pending > 0 && tab !== 'live' && (
                <span className="ml-1.5 rounded-full bg-amber-400 px-1.5 text-[10px] font-bold text-amber-950">{pending}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2 min-[1400px]:gap-2.5">
          <button type="button" onClick={() => setTab('audit')} title={chain?.head ? `Head ${chain.head}` : undefined}
            className={cx('flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12.5px] font-semibold ring-1',
              !chain ? 'bg-white/10 ring-white/20' : chain.valid ? 'bg-emerald-500/20 text-emerald-50 ring-emerald-300/40' : 'bg-red-500 text-white ring-red-300')}>
            {chain && !chain.valid ? <ShieldAlert className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4 text-emerald-300" />}
            {!chain ? 'Audit chain…' : chain.valid
              ? <><span className="hidden min-[1400px]:inline">Chain verified ·</span><span className="min-[1400px]:hidden">Verified ·</span> {num(chain.checked)} entries <span className="hidden font-mono text-[11px] font-normal text-emerald-100/80 min-[1400px]:inline"><Link2 className="mb-px inline h-3 w-3" /> {short(chain.head, 6)}</span></>
              : <>Chain broken at #{chain.broken_at_seq}</>}
          </button>
          <Counter label="Confirmed" title="Confirmed orders (auto or human-approved)" value={o.CONFIRMED?.count ?? 0} dot="bg-emerald-400" />
          <Counter label="Pending" title="Waiting for a human approver" value={o.PENDING_APPROVAL?.count ?? 0} dot="bg-amber-400" />
          <Counter label="Blocked" title="Blocked by guardrails or rejected by the approver" value={o.REJECTED?.count ?? 0} dot="bg-red-400" />
          <div className="flex items-center gap-2 rounded-lg bg-white/10 px-3 py-1.5 ring-1 ring-white/15" title="Calls to the Valio Aimo price & availability API">
            <Activity className="h-4 w-4 text-valio-100" />
            <div className="leading-none">
              <div className="text-[15px] font-bold tabular-nums">{num(stats?.valio_api_calls ?? 0)}</div>
              <div className="mt-0.5 text-[10px] uppercase tracking-wide text-valio-100">Valio API</div>
            </div>
          </div>
          <span title={connected ? 'Live stream connected' : 'Reconnecting to live stream…'}
            className={cx('ml-1 h-2.5 w-2.5 rounded-full', connected ? 'live-dot bg-emerald-400' : 'bg-slate-400')} />
        </div>
      </div>
    </header>
  )
}

function Counter({ label, value, dot, title }: { label: string; value: number; dot: string; title?: string }) {
  return (
    <div title={title} className="flex items-center gap-2 rounded-lg bg-white/10 px-2.5 py-1.5 ring-1 ring-white/15">
      <span className={cx('h-2 w-2 rounded-full', dot)} />
      <div className="leading-none">
        <div className="text-[15px] font-bold tabular-nums">{value}</div>
        <div className="mt-0.5 text-[10px] uppercase tracking-wide text-valio-100">{label}</div>
      </div>
    </div>
  )
}
