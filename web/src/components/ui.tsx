import {
  AlertTriangle, Bot, CheckCircle2, ChevronDown, ChevronRight, Clock, Info, ShieldCheck, ShieldX, User, X, XCircle,
} from 'lucide-react'
import { Fragment, useState, type ReactNode } from 'react'
import { actorKind } from '../lib/format'
import type { Order } from '../types'

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

// ------------------------------------------------------------------ status
export type Tone = 'green' | 'amber' | 'red' | 'blue' | 'slate'

export const toneClasses: Record<Tone, string> = {
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  amber: 'bg-amber-50 text-amber-800 ring-amber-600/25',
  red: 'bg-red-50 text-red-700 ring-red-600/20',
  blue: 'bg-valio-50 text-valio-700 ring-valio-600/20',
  slate: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

/** One mapping for every status/outcome string so colours are consistent everywhere. */
export function statusInfo(s: string | null | undefined, order?: Order | null): { label: string; tone: Tone } {
  switch ((s || '').toUpperCase()) {
    case 'CONFIRMED':
      return { label: 'Confirmed', tone: 'green' }
    case 'AUTO':
      return { label: 'Auto-approved', tone: 'green' }
    case 'APPROVED':
      return { label: 'Approved', tone: 'green' }
    case 'PENDING_APPROVAL':
    case 'PENDING':
      return { label: 'Pending approval', tone: 'amber' }
    case 'APPROVAL':
      return { label: 'Needs approval', tone: 'amber' }
    case 'BLOCKED':
      return { label: 'Blocked', tone: 'red' }
    case 'REJECTED':
      return order?.decision?.outcome === 'BLOCKED' ? { label: 'Blocked', tone: 'red' } : { label: 'Rejected', tone: 'red' }
    default:
      return { label: s || 'Unknown', tone: 'slate' }
  }
}

const toneIcon: Record<Tone, typeof CheckCircle2> = {
  green: CheckCircle2, amber: Clock, red: XCircle, blue: Info, slate: Info,
}

export function StatusPill({ status, order, size = 'sm' }: { status?: string | null; order?: Order | null; size?: 'sm' | 'lg' }) {
  const { label, tone } = statusInfo(status, order)
  const Icon = toneIcon[tone]
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-full font-semibold ring-1 ring-inset whitespace-nowrap',
      toneClasses[tone], size === 'lg' ? 'px-3.5 py-1.5 text-sm uppercase tracking-wide' : 'px-2 py-0.5 text-xs')}>
      <Icon className={size === 'lg' ? 'h-4 w-4' : 'h-3.5 w-3.5'} />
      {label}
    </span>
  )
}

export function Badge({ children, tone = 'slate', className }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset whitespace-nowrap', toneClasses[tone], className)}>
      {children}
    </span>
  )
}

const tierTone: Record<string, string> = {
  good: 'bg-sky-50 text-sky-700 ring-sky-600/20',
  better: 'bg-indigo-50 text-indigo-700 ring-indigo-600/20',
  best: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  alternative: 'bg-slate-100 text-slate-600 ring-slate-500/20',
  split: 'bg-violet-50 text-violet-700 ring-violet-600/20',
}

export function TierBadge({ tier }: { tier?: string }) {
  const t = (tier || 'option').toLowerCase()
  return (
    <span className={cx('inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1 ring-inset',
      tierTone[t] || tierTone.alternative)}>
      {t === 'alternative' ? 'alt' : t}
    </span>
  )
}

export function SignedBadge({ label = 'Signed by Valio · EdDSA' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-valio-50 px-1.5 py-0.5 text-[11px] font-semibold text-valio-700 ring-1 ring-inset ring-valio-600/20">
      <ShieldCheck className="h-3.5 w-3.5" /> {label}
    </span>
  )
}

// ------------------------------------------------------------------ layout
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('rounded-xl bg-white shadow-sm ring-1 ring-slate-200/80', className)}>{children}</div>
}

export function SectionTitle({ icon, children, right }: { icon?: ReactNode; children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 px-1 pb-2">
      <h2 className="flex items-center gap-2 text-[13px] font-bold uppercase tracking-wider text-slate-500">
        {icon}
        {children}
      </h2>
      {right}
    </div>
  )
}

export function Collapsible({ title, children, defaultOpen = false, className }: {
  title: ReactNode; children: ReactNode; defaultOpen?: boolean; className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={className}>
      <button type="button" onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800">
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {title}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  )
}

export function ActorIcon({ actor, className }: { actor?: string | null; className?: string }) {
  const { kind } = actorKind(actor)
  const base = 'flex h-7 w-7 shrink-0 items-center justify-center rounded-full ring-1'
  if (kind === 'human')
    return <span className={cx(base, 'bg-amber-50 text-amber-700 ring-amber-200', className)}><User className="h-4 w-4" /></span>
  if (kind === 'gate')
    return <span className={cx(base, 'bg-valio-50 text-valio-600 ring-valio-200', className)}><ShieldCheck className="h-4 w-4" /></span>
  return <span className={cx(base, 'bg-slate-100 text-slate-600 ring-slate-200', className)}><Bot className="h-4 w-4" /></span>
}

export function ReasonList({ reasons, tone = 'amber' }: { reasons: string[]; tone?: 'amber' | 'red' }) {
  if (!reasons.length) return null
  const Icon = tone === 'red' ? ShieldX : AlertTriangle
  return (
    <ul className="space-y-1.5">
      {reasons.map((r, i) => (
        <li key={i} className="flex gap-2 text-[13px] leading-snug text-slate-700">
          <Icon className={cx('mt-0.5 h-4 w-4 shrink-0', tone === 'red' ? 'text-red-500' : 'text-amber-500')} />
          <span>{r}</span>
        </li>
      ))}
    </ul>
  )
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
      {icon && <div className="mb-3 text-slate-300">{icon}</div>}
      <div className="text-sm font-semibold text-slate-600">{title}</div>
      {children && <div className="mt-1 max-w-sm text-[13px] text-slate-500">{children}</div>}
    </div>
  )
}

// ------------------------------------------------------------------ markdown-ish text
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g
  let last = 0
  let m: RegExpExecArray | null
  let k = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const t = m[0]
    if (t.startsWith('**')) out.push(<strong key={k++} className="font-semibold text-slate-900">{t.slice(2, -2)}</strong>)
    else if (t.startsWith('`')) out.push(<code key={k++} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em]">{t.slice(1, -1)}</code>)
    else out.push(<em key={k++}>{t.slice(1, -1)}</em>)
    last = m.index + t.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** Paragraphs, bullet / numbered lists, headings, bold, italics, inline code, simple tables. */
export function Markdown({ text, className }: { text?: string; className?: string }) {
  if (!text) return null
  const lines = text.replace(/\r/g, '').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let k = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) {
      blocks.push(<div key={k++} className="mt-1 font-semibold text-slate-900">{inline(h[2])}</div>)
      i++
      continue
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line)
      const items: string[] = []
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ''))
        i++
        // continuation lines (indented, not a new bullet)
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
          items[items.length - 1] += ' ' + lines[i].trim()
          i++
        }
      }
      const L = ordered ? 'ol' : 'ul'
      blocks.push(
        <L key={k++} className={cx('space-y-1 pl-5', ordered ? 'list-decimal' : 'list-disc', 'marker:text-slate-400')}>
          {items.map((it, j) => <li key={j}>{inline(it)}</li>)}
        </L>,
      )
      continue
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows: string[][] = []
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        if (!/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().slice(1, -1).split('|').map((c) => c.trim()))
        i++
      }
      blocks.push(
        <div key={k++} className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <tbody>
              {rows.map((r, j) => (
                <tr key={j} className={j === 0 ? 'font-semibold text-slate-900' : 'border-t border-slate-200'}>
                  {r.map((c, n) => <td key={n} className="px-2 py-1">{inline(c)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i]) && !/^#{1,4}\s/.test(lines[i]) && !/^\s*\|.*\|\s*$/.test(lines[i])) {
      para.push(lines[i].trim())
      i++
    }
    blocks.push(<p key={k++}>{para.map((p, j) => <Fragment key={j}>{j > 0 && <br />}{inline(p)}</Fragment>)}</p>)
  }
  return <div className={cx('space-y-2', className)}>{blocks}</div>
}

// ------------------------------------------------------------------ toasts
export interface ToastMsg {
  id: number
  tone: 'error' | 'success' | 'info'
  title: string
  body?: string
}

export function Toasts({ toasts, dismiss }: { toasts: ToastMsg[]; dismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[400px] flex-col gap-2">
      {toasts.map((t) => (
        <div key={t.id} className={cx('anim-in pointer-events-auto flex gap-3 rounded-xl bg-white p-4 shadow-lg ring-1',
          t.tone === 'error' ? 'ring-red-200' : t.tone === 'success' ? 'ring-emerald-200' : 'ring-slate-200')}>
          {t.tone === 'error' ? <XCircle className="h-5 w-5 shrink-0 text-red-500" />
            : t.tone === 'success' ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
              : <Info className="h-5 w-5 shrink-0 text-valio-600" />}
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-slate-900">{t.title}</div>
            {t.body && <div className="mt-0.5 text-[13px] text-slate-600">{t.body}</div>}
          </div>
          <button type="button" onClick={() => dismiss(t.id)} className="self-start text-slate-400 hover:text-slate-700">
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  )
}
