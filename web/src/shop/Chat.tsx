import {
  AlertCircle, ArrowRight, CalendarClock, Check, CheckCircle2, Clock, Mic, MicOff, RotateCcw, SendHorizontal,
  ShieldCheck, Sparkles, XCircle,
} from 'lucide-react'
import { Fragment, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Markdown, cx } from '../components/ui'
import type { Customer, Message, Session } from './types'

interface Props {
  session: Session | null
  customer: Customer | null
  sending: boolean
  onSend: (text: string) => void
  onStanding: (id: string) => void
  onNew: () => void
}

export function Chat({ session, customer, sending, onSend, onStanding, onNew }: Props) {
  const msgs = session?.messages || []
  const busy = !!session?.busy || sending
  const scroller = useRef<HTMLDivElement>(null)
  const fresh = !msgs.some((m) => m.role === 'user')

  // keep the newest message in view
  useLayoutEffect(() => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [msgs.length, busy])

  const lastUser = msgs.map((m) => m.role).lastIndexOf('user')
  const lastProgress = msgs.map((m) => m.role).lastIndexOf('progress')
  const lastQuestion = msgs.map((m) => m.role).lastIndexOf('question')
  const spinningProgress = busy && lastProgress > lastUser && lastProgress === msgs.length - 1 ? lastProgress : -1

  // group consecutive progress rows into one activity block
  type Block = { kind: 'msg'; m: Message; i: number } | { kind: 'progress'; items: { m: Message; i: number }[] }
  const grouped: Block[] = []
  msgs.forEach((m, i) => {
    const prev = grouped[grouped.length - 1]
    if (m.role === 'progress') {
      if (prev && prev.kind === 'progress') prev.items.push({ m, i })
      else grouped.push({ kind: 'progress', items: [{ m, i }] })
    } else grouped.push({ kind: 'msg', m, i })
  })

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-slate-200/80 px-6 py-3">
        <div className="flex items-center gap-2.5">
          <AssistantAvatar />
          <div>
            <div className="text-[14px] font-semibold text-slate-900">Aimo Assistant</div>
            <div className="flex items-center gap-1.5 text-[11.5px] text-slate-500">
              <span className={cx('h-1.5 w-1.5 rounded-full', busy ? 'bg-amber-500' : 'bg-emerald-500')} />
              {busy ? 'Working on it…' : 'Live prices & stock from Valio Aimo'}
            </div>
          </div>
        </div>
        <button type="button" onClick={onNew} disabled={busy}
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 disabled:opacity-40">
          <RotateCcw className="h-3.5 w-3.5" /> New conversation
        </button>
      </div>

      <div ref={scroller} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
        {grouped.map((b) => b.kind === 'progress'
          ? <ProgressBlock key={b.items[0].m.id} items={b.items} spinning={spinningProgress} />
          : <MessageView key={b.m.id} m={b.m} openQuestion={b.i === lastQuestion && !!session?.question && !busy} onSend={onSend} />)}

        {busy && spinningProgress < 0 && <Thinking />}

        {fresh && !busy && customer && <StartHere customer={customer} onSend={onSend} onStanding={onStanding} />}
      </div>

      <Composer disabled={busy} onSend={onSend} placeholder={fresh ? 'e.g. “Lunch for 60 on Thursday: salmon soup and a salad”' : 'Reply to Aimo…'} />
    </div>
  )
}

export function AssistantAvatar({ size = 'md' }: { size?: 'sm' | 'md' }) {
  return (
    <div className={cx('grid shrink-0 place-items-center rounded-full bg-gradient-to-br from-[#0b2f6b] to-[#1f4fbf] text-white shadow-sm',
      size === 'sm' ? 'h-7 w-7' : 'h-9 w-9')}>
      <Sparkles className={size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'} />
    </div>
  )
}

function MessageView({ m, openQuestion, onSend }: { m: Message; openQuestion: boolean; onSend: (t: string) => void }) {
  switch (m.role) {
    case 'user':
      return (
        <div className="anim-in flex justify-end">
          <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-[#0b2f6b] px-4 py-2.5 text-[14px] leading-relaxed text-white shadow-sm">
            {m.text}
          </div>
        </div>
      )
    case 'assistant':
      return (
        <Bot>
          <div className="rounded-2xl rounded-tl-md bg-white px-4 py-3 text-[14px] leading-relaxed text-slate-700 shadow-sm ring-1 ring-slate-200/80">
            <Markdown text={m.text} />
          </div>
        </Bot>
      )
    case 'question':
      return (
        <Bot>
          <div className="rounded-2xl rounded-tl-md bg-white px-4 py-3 text-[14px] leading-relaxed text-slate-800 shadow-sm ring-1 ring-[#0b2f6b]/20">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#1f4fbf]">Quick question</div>
            <Markdown text={m.text} />
          </div>
          {openQuestion && (m.options?.length || 0) > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-2">
              {m.options!.map((o) => (
                <button key={o} type="button" onClick={() => onSend(o)}
                  className="anim-in rounded-full bg-white px-3.5 py-1.5 text-[13px] font-medium text-[#0b2f6b] shadow-sm ring-1 ring-[#0b2f6b]/25 transition hover:-translate-y-px hover:bg-[#0b2f6b] hover:text-white">
                  {o}
                </button>
              ))}
            </div>
          )}
        </Bot>
      )
    case 'notice':
      return <Bot><NoticeCard m={m} /></Bot>
    case 'error':
      return (
        <Bot>
          <div className="flex gap-2 rounded-xl bg-red-50 px-3.5 py-2.5 text-[13px] text-red-700 ring-1 ring-red-200">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> <span>{m.text}</span>
          </div>
        </Bot>
      )
    default:
      return null
  }
}

function Bot({ children }: { children: ReactNode }) {
  return (
    <div className="anim-in flex gap-2.5">
      <AssistantAvatar size="sm" />
      <div className="min-w-0 max-w-[90%] flex-1">{children}</div>
    </div>
  )
}

function NoticeCard({ m }: { m: Message }) {
  const s = (m.status || '').toUpperCase()
  const tone = s === 'CONFIRMED' ? 'green' : s === 'PENDING_APPROVAL' ? 'amber' : 'red'
  const Icon = tone === 'green' ? CheckCircle2 : tone === 'amber' ? Clock : XCircle
  const label = tone === 'green' ? 'Order confirmed' : tone === 'amber' ? 'Waiting for approval' : 'Not accepted'
  return (
    <div className={cx('rounded-xl px-4 py-3 ring-1',
      tone === 'green' && 'bg-emerald-50 ring-emerald-200', tone === 'amber' && 'bg-amber-50 ring-amber-200', tone === 'red' && 'bg-red-50 ring-red-200')}>
      <div className={cx('flex items-center gap-2 text-[13px] font-semibold',
        tone === 'green' && 'text-emerald-800', tone === 'amber' && 'text-amber-800', tone === 'red' && 'text-red-700')}>
        <Icon className="h-4 w-4" /> {label}
        {m.order_id && <span className="ml-auto font-mono text-[11px] font-normal opacity-70">{m.order_id}</span>}
      </div>
      <div className="mt-1 text-[13px] leading-relaxed text-slate-700">{m.text}</div>
      {tone === 'green' && (
        <div className="mt-1.5 flex items-center gap-1 text-[11.5px] font-medium text-emerald-700">
          <ShieldCheck className="h-3.5 w-3.5" /> Signed confirmation from Valio Aimo
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ progress ("what I did")
function ProgressBlock({ items, spinning }: { items: { m: Message; i: number }[]; spinning: number }) {
  return (
    <div className="anim-in ml-9 rounded-xl bg-slate-50/80 px-3.5 py-2.5 ring-1 ring-slate-200/70">
      <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">What I did</div>
      <ol className="space-y-1.5">
        {items.map(({ m, i }) => (
          <li key={m.id} className="anim-in flex items-start gap-2 text-[12.5px] leading-snug text-slate-600">
            {i === spinning
              ? <span className="mt-0.5 inline-block h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-[#1f4fbf] border-r-transparent" />
              : <span className="mt-0.5 grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full bg-emerald-500 text-white"><Check className="h-2.5 w-2.5" strokeWidth={3} /></span>}
            <ProgressText text={m.text} />
          </li>
        ))}
      </ol>
    </div>
  )
}

/** "Searched 17,546 products → 661 matches → …" becomes a little funnel with bold numbers. */
function ProgressText({ text }: { text: string }) {
  const parts = text.split(/\s*→\s*/)
  return (
    <span className="min-w-0">
      {parts.map((p, j) => (
        <Fragment key={j}>
          {j > 0 && <ArrowRight className="mx-1 inline h-3 w-3 -translate-y-px text-slate-400" />}
          <Numbers text={p} />
        </Fragment>
      ))}
    </span>
  )
}

function Numbers({ text }: { text: string }) {
  const out: ReactNode[] = []
  const re = /(€?\d[\d,.]*(?:\s?%)?)/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(<strong key={m.index} className="font-semibold tabular-nums text-slate-900">{m[0]}</strong>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return <>{out}</>
}

function Thinking() {
  return (
    <div className="anim-in flex items-center gap-2.5">
      <AssistantAvatar size="sm" />
      <div className="flex items-center gap-1 rounded-2xl rounded-tl-md bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200/80">
        {[0, 1, 2].map((d) => (
          <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#1f4fbf]/70" style={{ animationDelay: `${d * 140}ms` }} />
        ))}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ empty state
function StartHere({ customer, onSend, onStanding }: { customer: Customer; onSend: (t: string) => void; onStanding: (id: string) => void }) {
  const sos = customer.standing_orders || []
  const sugg = customer.suggestions || []
  return (
    <div className="anim-in ml-9 space-y-4 pt-1">
      {sugg.length > 0 && (
        <div>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Try asking</div>
          <div className="grid gap-2">
            {sugg.map((s) => (
              <button key={s} type="button" onClick={() => onSend(s)}
                className="group flex items-start gap-2.5 rounded-xl bg-white px-3.5 py-2.5 text-left text-[13px] leading-snug text-slate-700 shadow-sm ring-1 ring-slate-200 transition hover:-translate-y-px hover:ring-[#1f4fbf]/40 hover:shadow">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#1f4fbf]/60 group-hover:text-[#1f4fbf]" />
                <span>{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      {sos.length > 0 && (
        <div>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Your standing orders</div>
          <div className="grid gap-2">
            {sos.map((so) => (
              <div key={so.id} className="flex items-center gap-3 rounded-xl bg-white px-3.5 py-3 shadow-sm ring-1 ring-slate-200">
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[#eef3fc] text-[#0b2f6b]"><CalendarClock className="h-4.5 w-4.5" /></div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13.5px] font-semibold text-slate-800">{so.name}</div>
                  <div className="text-[12px] text-slate-500">{so.lines.length} items · {so.weekdays.map((d) => d.slice(0, 3)).join('/')}</div>
                </div>
                <button type="button" onClick={() => onStanding(so.id)}
                  className="shrink-0 rounded-lg bg-[#eef3fc] px-3 py-1.5 text-[12.5px] font-semibold text-[#0b2f6b] transition hover:bg-[#0b2f6b] hover:text-white">
                  Check my standing order
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ composer (+ voice)
type SR = { lang: string; interimResults: boolean; continuous: boolean; start: () => void; stop: () => void
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null; onerror: (() => void) | null }

function getSR(): (new () => SR) | null {
  const w = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR }
  return w.SpeechRecognition || w.webkitSpeechRecognition || null
}

function Composer({ disabled, onSend, placeholder }: { disabled: boolean; onSend: (t: string) => void; placeholder: string }) {
  const [text, setText] = useState('')
  const [listening, setListening] = useState(false)
  const ta = useRef<HTMLTextAreaElement>(null)
  const rec = useRef<SR | null>(null)
  const base = useRef('')
  const SRClass = getSR()

  useEffect(() => {
    const el = ta.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [text])

  const submit = () => {
    const t = text.trim()
    if (!t || disabled) return
    rec.current?.stop()
    onSend(t)
    setText('')
  }

  const toggleMic = () => {
    if (!SRClass) return
    if (listening) {
      rec.current?.stop()
      return
    }
    const r = new SRClass()
    r.lang = 'en-US'
    r.interimResults = true
    r.continuous = true
    base.current = text ? text.trimEnd() + ' ' : ''
    r.onresult = (e) => {
      let s = ''
      for (let i = 0; i < e.results.length; i++) s += e.results[i][0].transcript
      setText(base.current + s)
    }
    r.onend = () => setListening(false)
    r.onerror = () => setListening(false)
    rec.current = r
    r.start()
    setListening(true)
  }

  return (
    <div className="border-t border-slate-200/80 bg-white/70 px-5 py-3.5 backdrop-blur">
      <div className={cx('flex items-end gap-2 rounded-2xl bg-white p-2 shadow-sm ring-1 transition',
        listening ? 'ring-2 ring-red-300' : 'ring-slate-200 focus-within:ring-2 focus-within:ring-[#1f4fbf]/40')}>
        <textarea ref={ta} rows={1} value={text} onChange={(e) => setText(e.target.value)} placeholder={listening ? 'Listening… just speak' : placeholder}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit()
            }
          }}
          className="max-h-40 min-h-[40px] flex-1 resize-none border-0 bg-transparent px-2 py-2 text-[14px] text-slate-800 placeholder:text-slate-400 focus:outline-none" />
        {SRClass && (
          <button type="button" onClick={toggleMic} title={listening ? 'Stop listening' : 'Speak your order'}
            className={cx('grid h-10 w-10 shrink-0 place-items-center rounded-xl transition',
              listening ? 'live-mic bg-red-500 text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-[#0b2f6b]')}>
            {listening ? <MicOff className="h-4.5 w-4.5" /> : <Mic className="h-4.5 w-4.5" />}
          </button>
        )}
        <button type="button" onClick={submit} disabled={disabled || !text.trim()} title="Send"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#0b2f6b] text-white shadow-sm transition hover:bg-[#123d86] disabled:bg-slate-200 disabled:text-slate-400">
          <SendHorizontal className="h-4.5 w-4.5" />
        </button>
      </div>
      <div className="mt-1.5 px-1 text-[11px] text-slate-400">
        Enter to send · Shift+Enter for a new line{SRClass ? ' · or tap the mic and just speak' : ''}
      </div>
    </div>
  )
}
