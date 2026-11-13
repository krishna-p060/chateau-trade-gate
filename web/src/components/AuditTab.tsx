import { ArrowRight, ChevronDown, ChevronRight, FileText, Filter, Link2, ListTree, RefreshCw, ShieldAlert, ShieldCheck, X } from 'lucide-react'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { actorKind, clock, day, num, short } from '../lib/format'
import { shortBuyer } from '../lib/mandates'
import type { AuditEntry, Buyer, Integrity } from '../types'
import { Spinner } from './ToolSteps'
import { ActorIcon, Card, Empty, cx } from './ui'

interface Props {
  audit: AuditEntry[]
  buyers: Buyer[]
  refFilter: string
  setRefFilter: (r: string) => void
}

const eventTone = (e: string) => {
  if (e === 'order.confirmed' || e === 'approval.approved') return 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
  if (e === 'approval.requested') return 'bg-amber-50 text-amber-800 ring-amber-600/25'
  if (e === 'approval.rejected' || e === 'quote.refused') return 'bg-red-50 text-red-700 ring-red-600/20'
  if (e === 'policy.decision') return 'bg-valio-50 text-valio-700 ring-valio-600/20'
  return 'bg-slate-100 text-slate-600 ring-slate-500/20'
}

function policyTone(a: AuditEntry): string | null {
  if (a.event !== 'policy.decision') return null
  const d = a.data as { outcome?: string } | null
  const o = d?.outcome || (/blocked/i.test(a.summary) ? 'BLOCKED' : /approval/i.test(a.summary) ? 'APPROVAL' : 'AUTO')
  return o === 'BLOCKED' ? 'bg-red-50 text-red-700 ring-red-600/20' : o === 'APPROVAL' ? 'bg-amber-50 text-amber-800 ring-amber-600/25' : 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
}

export function AuditTab({ audit, buyers, refFilter, setRefFilter }: Props) {
  const [buyer, setBuyer] = useState('')
  const [view, setView] = useState<'log' | 'report'>('log')
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [check, setCheck] = useState<{ busy: boolean; result: Integrity | null; at?: string }>({ busy: false, result: null })
  const [narrative, setNarrative] = useState<{ text: string; busy: boolean }>({ text: '', busy: false })
  const [refInput, setRefInput] = useState(refFilter)
  useEffect(() => setRefInput(refFilter), [refFilter])

  const rows = useMemo(() => {
    const r = refFilter.trim()
    return audit
      .filter((a) => !buyer || a.buyer_id === buyer)
      .filter((a) => !r || a.ref === r || JSON.stringify(a.data ?? '').includes(r))
      .sort((a, b) => b.seq - a.seq)
  }, [audit, buyer, refFilter])

  const verify = async () => {
    setCheck({ busy: true, result: check.result })
    try {
      const r = await api.audit({ since: 1_000_000_000 })
      // a short pause so the check is visible on screen
      await new Promise((ok) => setTimeout(ok, 450))
      setCheck({ busy: false, result: r.integrity, at: new Date().toLocaleTimeString('en-GB') })
    } catch (e) {
      setCheck({ busy: false, result: { valid: false }, at: (e as Error).message })
    }
  }

  useEffect(() => {
    if (view !== 'report') return
    let alive = true
    setNarrative((n) => ({ ...n, busy: true }))
    api.narrative({ buyer_id: buyer || undefined, ref: refFilter.trim() || undefined })
      .then((r) => alive && setNarrative({ text: r?.text || '', busy: false }))
      .catch(() => alive && setNarrative({ text: '', busy: false }))
    return () => { alive = false }
  }, [view, buyer, refFilter, audit.length])

  return (
    <div className="mx-auto flex h-full max-w-[1280px] min-h-0 flex-col gap-4">
      <div className="flex items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-slate-900">What happened and why</h1>
          <p className="mt-0.5 text-[13px] text-slate-500">Every search, quote, guardrail decision and human approval is appended to a SHA-256 hash chain. Change one entry and every later hash breaks.</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {check.result && !check.busy && (
            <div className={cx('anim-in flex items-center gap-2 whitespace-nowrap rounded-xl px-4 py-2 text-[13px] ring-1',
              check.result.valid ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : 'bg-red-50 text-red-800 ring-red-200')}>
              {check.result.valid ? <ShieldCheck className="h-5 w-5 text-emerald-600" /> : <ShieldAlert className="h-5 w-5 text-red-600" />}
              <div className="leading-tight">
                <div className="font-bold">{check.result.valid ? `Chain intact: ${num(check.result.checked)} entries` : check.result.broken_at_seq ? `Broken at #${check.result.broken_at_seq}` : 'Verification failed'}</div>
                <div className="font-mono text-[11px] opacity-75">{check.result.valid ? `head ${short(check.result.head, 12)}… · ${check.at}` : check.at}</div>
              </div>
            </div>
          )}
          <button type="button" onClick={verify} disabled={check.busy}
            className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-xl bg-valio-600 px-4 py-2.5 text-[13.5px] font-semibold text-white shadow-sm transition hover:bg-valio-700 disabled:opacity-70">
            {check.busy ? <Spinner className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />} Verify integrity
          </button>
        </div>
      </div>

      <Card className="flex flex-wrap items-center gap-3 px-4 py-2.5">
        <Filter className="h-4 w-4 text-slate-400" />
        <select value={buyer} onChange={(e) => setBuyer(e.target.value)}
          className="rounded-lg border-0 bg-slate-50 py-1.5 pl-2.5 pr-8 text-[13px] text-slate-700 ring-1 ring-slate-200">
          <option value="">All buyers</option>
          {buyers.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <form className="flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); setRefFilter(refInput.trim()) }}>
          <input value={refInput} onChange={(e) => setRefInput(e.target.value)} placeholder="Order or quote ref, e.g. ord_…"
            className="w-64 rounded-lg border-0 bg-slate-50 px-2.5 py-1.5 font-mono text-[12.5px] text-slate-700 ring-1 ring-slate-200 focus:ring-2 focus:ring-valio-500 focus:outline-none" />
          {refFilter && (
            <button type="button" onClick={() => setRefFilter('')} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="Clear">
              <X className="h-4 w-4" />
            </button>
          )}
        </form>
        <span className="text-[12.5px] text-slate-500">{num(rows.length)} entries</span>
        <div className="ml-auto flex rounded-lg bg-slate-100 p-0.5">
          {([['log', 'Hash-chained log', ListTree], ['report', 'Plain-language report', FileText]] as const).map(([v, label, Icon]) => (
            <button type="button" key={v} onClick={() => setView(v)}
              className={cx('flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-semibold',
                view === v ? 'bg-white text-valio-700 shadow-sm' : 'text-slate-500 hover:text-slate-800')}>
              <Icon className="h-3.5 w-3.5" />{label}
            </button>
          ))}
        </div>
      </Card>

      <Card className="min-h-0 flex-1 overflow-hidden">
        {view === 'log' ? (
          <div className="h-full overflow-y-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="sticky top-0 z-10 bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500 shadow-[0_1px_0_#e2e8f0]">
                <tr>
                  <th className="w-8" />
                  <th className="px-2 py-2 font-semibold">#</th>
                  <th className="px-2 py-2 font-semibold">Time</th>
                  <th className="px-2 py-2 font-semibold">Actor</th>
                  <th className="px-2 py-2 font-semibold">Event</th>
                  <th className="px-2 py-2 font-semibold">What happened</th>
                  <th className="px-2 py-2 font-semibold">Ref</th>
                  <th className="px-3 py-2 font-semibold">Hash</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const isOpen = open.has(a.seq)
                  const actor = actorKind(a.actor)
                  return (
                    <Fragment key={a.seq}>
                      <tr onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(a.seq)) n.delete(a.seq); else n.add(a.seq); return n })}
                        className={cx('anim-in cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50', isOpen && 'bg-slate-50')}>
                        <td className="py-2.5 pl-3 text-slate-400">{isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</td>
                        <td className="px-2 py-2.5 font-mono text-[12px] text-slate-400">{a.seq}</td>
                        <td className="whitespace-nowrap px-2 py-2.5 text-[12px] text-slate-500">
                          <div className="font-mono">{clock(a.ts)}</div>
                          <div className="text-[11px] text-slate-400">{day(a.ts?.slice(0, 10))}</div>
                        </td>
                        <td className="px-2 py-2.5">
                          <div className="flex items-center gap-2">
                            <ActorIcon actor={a.actor} />
                            <div className="min-w-0 leading-tight">
                              <div className="max-w-[170px] truncate text-[12.5px] font-semibold text-slate-800" title={actor.name}>{actor.name}</div>
                              <div className="text-[11px] text-slate-400">{actor.kind === 'agent' ? `agent · ${shortBuyer(a.buyer_id, buyers)}` : actor.kind === 'human' ? 'human approver' : 'Valio gate'}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-2 py-2.5">
                          <span className={cx('inline-flex whitespace-nowrap rounded-md px-1.5 py-0.5 font-mono text-[11px] ring-1 ring-inset', policyTone(a) || eventTone(a.event))}>{a.event}</span>
                        </td>
                        <td className="px-2 py-2.5 leading-snug text-slate-700">{a.summary}</td>
                        <td className="px-2 py-2.5">
                          {a.ref && (
                            <button type="button" onClick={(e) => { e.stopPropagation(); setRefFilter(a.ref || '') }}
                              className="whitespace-nowrap font-mono text-[11.5px] text-valio-600 hover:underline">{a.ref}</button>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[11px] text-slate-400">
                          <Link2 className="mb-px mr-1 inline h-3 w-3" />{short(a.hash, 8)}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-slate-50">
                          <td />
                          <td colSpan={7} className="px-2 pb-4 pt-1">
                            <div className="mb-2 flex flex-wrap items-center gap-2 font-mono text-[12px]">
                              <span className="text-slate-400">prev</span>
                              <span className="rounded bg-white px-1.5 py-0.5 text-slate-600 ring-1 ring-slate-200" title={a.prev_hash}>{short(a.prev_hash)}…</span>
                              <ArrowRight className="h-3.5 w-3.5 text-slate-400" />
                              <span className="text-slate-400">hash</span>
                              <span className="rounded bg-white px-1.5 py-0.5 font-semibold text-valio-700 ring-1 ring-valio-200" title={a.hash}>{short(a.hash)}…</span>
                              <span className="font-sans text-[11.5px] text-slate-400">SHA-256 over seq, time, buyer, actor, event, summary, ref, data and prev hash</span>
                            </div>
                            <pre className="max-h-80 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11.5px] leading-relaxed text-slate-100">{JSON.stringify(a.data, null, 2)}</pre>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
            {rows.length === 0 && <Empty icon={<ListTree className="h-8 w-8" />} title="No audit entries match">Try clearing the filters.</Empty>}
          </div>
        ) : (
          <div className="h-full overflow-y-auto px-6 py-5">
            <div className="mb-3 flex items-center gap-2 text-[13px] text-slate-500">
              <FileText className="h-4 w-4" />
              Report generated from the audit chain{buyer ? ` for ${shortBuyer(buyer, buyers)}` : ''}{refFilter ? ` · ${refFilter}` : ''}
              {narrative.busy && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
            </div>
            <Narrative text={narrative.text} />
          </div>
        )}
      </Card>
    </div>
  )
}

function Narrative({ text }: { text: string }) {
  const lines = text.split('\n').filter((l) => l.trim())
  if (!lines.length) return <Empty title="Nothing to report yet" />
  return (
    <ol className="space-y-2.5">
      {lines.map((l, i) => {
        const m = /^(\d{2}:\d{2}:\d{2})\s+\[([^\]]+)\]\s+(.*)$/.exec(l)
        if (!m) return <li key={i} className="text-[13.5px] text-slate-700">{l}</li>
        const actor = actorKind(m[2])
        return (
          <li key={i} className="flex items-start gap-3">
            <span className="w-16 shrink-0 pt-1 font-mono text-[12px] text-slate-400">{m[1]}</span>
            <ActorIcon actor={m[2]} />
            <div className="pt-0.5 text-[13.5px] leading-relaxed text-slate-700">
              <span className={cx('font-semibold', actor.kind === 'human' ? 'text-amber-800' : actor.kind === 'gate' ? 'text-valio-700' : 'text-slate-900')}>{actor.name}</span>
              <span className="text-slate-400"> · </span>{m[3]}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
