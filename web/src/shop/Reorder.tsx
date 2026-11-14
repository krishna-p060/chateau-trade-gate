import { AlertTriangle, ArrowRight, Bell, ShieldAlert, CalendarClock, CheckCircle2, History, Mail, MessageSquare, RotateCcw, Smartphone, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Spinner } from '../components/ToolSteps'
import { cx } from '../components/ui'
import { cutoffText } from './format'
import { fDay as day, fEur as eur, t, tn } from './i18n'
import type { Reminder, ReorderItem, ReorderOverview } from './types'

export const SCALES: { v: number; label: () => string }[] = [
  { v: 0.8, label: () => '−20%' },
  { v: 1, label: () => t('scale_usual') },
  { v: 1.2, label: () => '+20%' },
  { v: 1.5, label: () => '+50%' },
  { v: 2, label: () => '×2' },
]

export type RepeatFn = (source: string, scale: number, auto: boolean) => Promise<void>

/** −20% / Usual / +20% / +50% / ×2 — for a quiet week or a busy one. */
export function ScaleChips({ value, onChange, disabled, size = 'md' }: {
  value: number; onChange: (v: number) => void; disabled?: boolean; size?: 'sm' | 'md'
}) {
  return (
    <div role="group" aria-label={t('qty_label')} className="inline-flex rounded-xl bg-slate-100 p-1">
      {SCALES.map((s) => (
        <button key={s.v} type="button" disabled={disabled} aria-pressed={value === s.v} onClick={() => onChange(s.v)}
          className={cx('rounded-lg font-semibold tabular-nums transition disabled:opacity-50',
            size === 'sm' ? 'px-2.5 py-1 text-[12px]' : 'px-3.5 py-1.5 text-[13.5px]',
            value === s.v ? 'bg-white text-[#0b2f6b] shadow-sm' : 'text-slate-500 hover:text-slate-800')}>
          {s.label()}
        </button>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ start screen: the usual order first
export function QuickStart({ overview, loading, busy, onRepeat }: {
  overview: ReorderOverview | null; loading: boolean; busy: boolean; onRepeat: RepeatFn
}) {
  const next = overview?.next ?? null
  const others = (overview?.templates || []).filter((x) => x.source !== next?.source)
  const recent = overview?.recent || []
  if (loading && !overview) {
    return (
      <div className="flex items-center justify-center gap-3 rounded-2xl bg-white px-6 py-10 text-[14px] text-slate-500 ring-1 ring-slate-200">
        <Spinner className="h-4 w-4 text-[#1f4fbf]" />{t('checking_usual')}
      </div>
    )
  }
  return (
    <div className="space-y-5">
      {next && <UsualCard item={next} busy={busy} onRepeat={onRepeat} />}
      {others.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-[13px] text-slate-500">
          <span>{t('other_templates')}:</span>
          {others.map((o) => (
            <button key={o.source} type="button" disabled={busy} onClick={() => onRepeat(o.source, 1, false)}
              className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 font-medium text-[#0b2f6b] ring-1 ring-slate-200 transition hover:bg-[#eef3fc] disabled:opacity-50">
              <CalendarClock className="h-3.5 w-3.5" />{o.name} · {day(o.deliver_by)}
            </button>
          ))}
        </div>
      )}
      {recent.length > 0 && <Recent items={recent} busy={busy} onRepeat={onRepeat} />}
    </div>
  )
}

function UsualCard({ item, busy, onRepeat }: { item: ReorderItem; busy: boolean; onRepeat: RepeatFn }) {
  const [scale, setScale] = useState(1)
  const [going, setGoing] = useState<'auto' | 'review' | null>(null)
  const problems = item.problems || []
  const ready = problems.length === 0
  const flags = item.flags || []
  const approval = flags.some((f) => f.level === 'warn')
  const total = item.total * scale
  const go = async (auto: boolean) => {
    setGoing(auto ? 'auto' : 'review')
    await onRepeat(item.source, scale, auto)
    setGoing(null)
  }
  return (
    <div className="anim-in overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
      <div className="px-6 pb-4 pt-5">
        <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wider text-[#1f4fbf]">
          <CalendarClock className="h-4 w-4" />{t('next_order')}
        </div>
        <div className="mt-1.5 flex items-baseline justify-between gap-4">
          <h2 className="min-w-0 truncate text-[22px] font-semibold text-slate-900">{item.name}</h2>
          <span className="shrink-0 text-[15px] font-semibold text-slate-700">{day(item.deliver_by)}</span>
        </div>
        <div className="mt-1 text-[14px] text-slate-600">
          {tn('products_about_one', 'products_about_other', item.lines_n, { total: eur(total, true) })}
          {item.order_by && <> · {t('order_by_short', { d: cutoffText(item.order_by) })}</>}
        </div>
        <div className="mt-1 truncate text-[12.5px] text-slate-400">{item.names.slice(0, 4).join(' · ')}{item.lines_n > 4 ? ' …' : ''}</div>

        <div className={cx('mt-3 flex items-start gap-2 rounded-xl px-3.5 py-2.5 text-[13.5px] font-medium',
          ready ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-900')}>
          {ready ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
          <div className="min-w-0">
            {ready ? t('all_available') : tn('n_unavailable_one', 'n_unavailable_other', problems.length)}
            {!ready && <div className="mt-0.5 truncate text-[12.5px] font-normal text-amber-800/80">{problems.map((p) => p.name).join(' · ')}</div>}
          </div>
        </div>
        {flags.map((f) => (
          <div key={f.label} className={cx('mt-2 flex items-center gap-2 px-1 text-[13px] font-medium', f.level === 'block' ? 'text-red-700' : 'text-amber-800')}>
            <ShieldAlert className="h-4 w-4 shrink-0" />{f.label}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 bg-slate-50/60 px-6 py-3.5">
        <ScaleChips value={scale} onChange={setScale} disabled={busy} />
        <div className="ml-auto flex items-center gap-2">
          {ready && (
            <button type="button" disabled={busy} onClick={() => go(false)}
              className="rounded-xl px-4 py-2.5 text-[14px] font-semibold text-[#0b2f6b] ring-1 ring-slate-300 transition hover:bg-white disabled:opacity-50">
              {going === 'review' ? <Spinner className="h-4 w-4" /> : t('look_change')}
            </button>
          )}
          <button type="button" disabled={busy} onClick={() => go(ready)}
            className={cx('flex items-center gap-2 rounded-xl px-6 py-2.5 text-[15px] font-semibold text-white shadow-sm transition disabled:bg-slate-300',
              ready ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-amber-600 hover:bg-amber-700')}>
            {going && <Spinner className="h-4 w-4" />}
            {!ready ? tn('review_changes_one', 'review_changes_other', problems.length) : approval ? t('send_approval') : t('order_as_usual')}
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

function Recent({ items, busy, onRepeat }: { items: ReorderItem[]; busy: boolean; onRepeat: RepeatFn }) {
  const [going, setGoing] = useState<string | null>(null)
  const label = (r: ReorderItem) => r.name || t(r.kind === 'event' ? 'kind_event' : r.kind === 'template' ? 'kind_template' : 'kind_order')
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wider text-slate-400">
        <History className="h-3.5 w-3.5" />{t('recent_title')}
      </div>
      <div className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-white ring-1 ring-slate-200">
        {items.map((r) => (
          <div key={r.source} className="flex items-center gap-4 px-4 py-2.5">
            <div className="w-24 shrink-0 text-[13px] font-medium text-slate-500">{day(r.day)}</div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[14px] font-medium text-slate-800">{label(r)}</div>
              <div className="truncate text-[12px] text-slate-400">
                {tn('products_about_one', 'products_about_other', r.lines_n, { total: eur(r.total, true) })}
                {r.problems.length > 0 && <span className="text-amber-700"> · {tn('n_unavailable_short_one', 'n_unavailable_short_other', r.problems.length)}</span>}
              </div>
            </div>
            <button type="button" disabled={busy} onClick={async () => { setGoing(r.source); await onRepeat(r.source, 1, false); setGoing(null) }}
              className="flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-semibold text-[#0b2f6b] ring-1 ring-slate-200 transition hover:bg-[#eef3fc] disabled:opacity-50">
              {going === r.source ? <Spinner className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}{t('order_again')}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ one tap, with a few seconds to undo
export function AutoConfirmBar({ until, onUndo, onNow, total, approval }: {
  until: number; onUndo: () => void; onNow: () => void; total: string; approval: boolean
}) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 200)
    return () => window.clearInterval(id)
  }, [])
  const left = Math.max(0, Math.ceil((until - now) / 1000))
  const pct = Math.min(100, Math.max(0, 100 - ((until - now) / 5000) * 100))
  return (
    <div className="relative shrink-0 overflow-hidden border-t border-emerald-200 bg-emerald-50 px-8 py-3.5">
      <div className="absolute inset-y-0 left-0 bg-emerald-100 transition-[width] duration-200" style={{ width: `${pct}%` }} />
      <div className="relative flex items-center gap-4">
        <Spinner className="h-5 w-5 text-emerald-700" />
        <span className="text-[15px] font-semibold text-emerald-900">{t(approval ? 'sending_in' : 'placing_in', { n: left })} · {total}</span>
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={onUndo}
            className="flex items-center gap-1.5 rounded-xl bg-white px-5 py-2 text-[14px] font-semibold text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50">
            <X className="h-4 w-4" />{t('undo')}
          </button>
          <button type="button" onClick={onNow}
            className="rounded-xl bg-emerald-600 px-5 py-2 text-[14px] font-semibold text-white hover:bg-emerald-700">{t('order_now')}</button>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ weekly reminder (preview of the message)
export function ReminderBell({ reminder, channel, onConfirm, onReview }: {
  reminder: Reminder | null; channel: string; onConfirm: (source: string) => void; onReview: (source: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])
  const on = !!reminder && channel !== 'off'
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(!open)} title={t('reminder_title')}
        className="relative grid h-9 w-9 place-items-center rounded-lg text-slate-500 transition hover:bg-slate-50 hover:text-[#0b2f6b]">
        <Bell className="h-[18px] w-[18px]" />
        {on && <span className="absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full bg-amber-500 ring-2 ring-white" />}
      </button>
      {open && (
        <div className="anim-in absolute right-0 top-full z-30 mt-2 w-[380px] whitespace-normal rounded-2xl bg-white p-4 shadow-xl ring-1 ring-slate-200">
          <div className="flex items-center gap-2 text-[13px] font-semibold text-slate-900">
            <Bell className="h-4 w-4 text-[#1f4fbf]" />{t('reminder_title')}
          </div>
          {!on || !reminder ? (
            <p className="mt-2 text-[13px] text-slate-500">{t('reminder_off_msg')}</p>
          ) : (
            <>
              <p className="mt-1 text-[12px] text-slate-500">
                {t(channel === 'email' ? 'reminder_when_email' : 'reminder_when_sms', { when: cutoffText(reminder.send_at) })}
              </p>
              <ReminderMessage reminder={reminder} channel={channel}
                onConfirm={() => { setOpen(false); onConfirm(reminder.source) }}
                onReview={() => { setOpen(false); onReview(reminder.source) }} />
              <p className="mt-2.5 text-[11.5px] leading-snug text-slate-400">{t('rem_production')}</p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function ReminderMessage({ reminder, channel, onConfirm, onReview }: {
  reminder: Reminder; channel: string; onConfirm: () => void; onReview: () => void
}) {
  const buttons = (
    <div className="mt-3 flex gap-2">
      {reminder.ready && (
        <button type="button" onClick={onConfirm}
          className="flex-1 rounded-xl bg-emerald-600 py-2 text-[13.5px] font-semibold text-white hover:bg-emerald-700">{t('rem_confirm')}</button>
      )}
      <button type="button" onClick={onReview}
        className={cx('flex-1 rounded-xl py-2 text-[13.5px] font-semibold',
          reminder.ready ? 'bg-white text-[#0b2f6b] ring-1 ring-slate-300 hover:bg-slate-50' : 'bg-amber-600 text-white hover:bg-amber-700')}>
        {t('rem_review')}
      </button>
    </div>
  )
  if (channel === 'email') {
    return (
      <div className="mt-3 overflow-hidden rounded-xl ring-1 ring-slate-200">
        <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-3.5 py-2 text-[12px] text-slate-500">
          <Mail className="h-3.5 w-3.5" /><span className="truncate"><b className="font-semibold text-slate-700">Valio Aimo</b> · {reminder.subject}</span>
        </div>
        <div className="px-3.5 py-3 text-[13.5px] leading-relaxed text-slate-800">{reminder.text}{buttons}</div>
      </div>
    )
  }
  return (
    <div className="mt-3 rounded-[22px] bg-slate-900 p-2.5">
      <div className="rounded-2xl bg-slate-100 px-3 pb-3 pt-2">
        <div className="mb-2 flex items-center justify-center gap-1.5 text-[11px] font-medium text-slate-500">
          <Smartphone className="h-3 w-3" />Valio Aimo
        </div>
        <div className="flex gap-2">
          <MessageSquare className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
          <div className="rounded-2xl rounded-tl-md bg-white px-3 py-2 text-[13.5px] leading-relaxed text-slate-800 shadow-sm">{reminder.text}</div>
        </div>
        {buttons}
      </div>
    </div>
  )
}
