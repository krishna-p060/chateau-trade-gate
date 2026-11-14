import {
  AlertCircle, Check, CheckCircle2, ChevronDown, Clock, Mic, MicOff, RotateCcw, SendHorizontal, Sparkles, XCircle,
} from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Markdown, cx } from '../components/ui'
import type { Message, Session } from './types'

interface Props {
  session: Session | null
  sending: boolean
  onSend: (text: string) => void
  onNew: () => void
}

type Block = { kind: 'msg'; m: Message } | { kind: 'steps'; items: Message[] }

/** The conversation log. The decisions themselves happen in the workspace on the right. */
export function Chat({ session, sending, onSend, onNew }: Props) {
  const msgs = session?.messages || []
  const busy = !!session?.busy || sending
  const scroller = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [msgs.length, busy])

  const blocks: Block[] = []
  msgs.forEach((m) => {
    const prev = blocks[blocks.length - 1]
    if (m.role === 'progress') {
      if (prev && prev.kind === 'steps') prev.items.push(m)
      else blocks.push({ kind: 'steps', items: [m] })
    } else blocks.push({ kind: 'msg', m })
  })
  const last = blocks[blocks.length - 1]

  const placeholder = session?.order ? 'Tell Aimo what you need…'
    : session?.question?.questions?.length ? 'Or type your answer…'
      : session?.plan?.status === 'proposed' && !session.cart ? 'Ask for a change to the list…'
        : session?.cart ? 'Ask for a change to the cart…'
          : 'Tell Aimo what you need…'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200/80 px-5">
        <div className="flex items-center gap-2">
          <AssistantAvatar />
          <span className="text-[13.5px] font-semibold text-slate-900">Aimo Assistant</span>
          <span className={cx('h-1.5 w-1.5 rounded-full', busy ? 'bg-amber-500' : 'bg-emerald-500')} />
        </div>
        <button type="button" onClick={onNew} disabled={busy}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 disabled:opacity-40">
          <RotateCcw className="h-3.5 w-3.5" /> New
        </button>
      </div>

      <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {blocks.map((b, i) => b.kind === 'steps'
          ? <Steps key={b.items[0].id} items={b.items} running={busy && b === last} />
          : <MessageView key={b.m.id} m={b.m} open={!!session?.question && i === blocks.length - 1} />)}
        {busy && last?.kind !== 'steps' && <Thinking />}
      </div>

      <Composer disabled={busy} onSend={onSend} placeholder={placeholder} />
    </div>
  )
}

export function AssistantAvatar() {
  return (
    <div className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#0b2f6b] text-white">
      <Sparkles className="h-3 w-3" />
    </div>
  )
}

function MessageView({ m, open }: { m: Message; open: boolean }) {
  switch (m.role) {
    case 'user':
      return (
        <div className="anim-in flex justify-end">
          <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-[#0b2f6b] px-3.5 py-2 text-[13.5px] leading-relaxed text-white">
            {m.text}
          </div>
        </div>
      )
    case 'assistant':
      return (
        <div className="anim-in max-w-[92%] rounded-2xl rounded-tl-md bg-white px-3.5 py-2.5 text-[13.5px] leading-relaxed text-slate-700 ring-1 ring-slate-200/80">
          <Markdown text={m.text} />
        </div>
      )
    case 'question': {
      const qs = m.questions?.length ? m.questions.map((q) => q.text) : [m.text]
      return (
        <div className="anim-in text-[12.5px] leading-snug text-slate-500">
          <span className="font-medium text-slate-600">Aimo asked:</span> {qs.join(' · ')}
          {open && <span className="text-[#1f4fbf]"> — answer on the right →</span>}
        </div>
      )
    }
    case 'notice':
      return <Notice m={m} />
    case 'error':
      return (
        <div className="anim-in flex gap-2 rounded-xl bg-red-50 px-3 py-2 text-[12.5px] text-red-700 ring-1 ring-red-200">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span>{m.text}</span>
        </div>
      )
    default:
      return null
  }
}

function Notice({ m }: { m: Message }) {
  const s = (m.status || '').toUpperCase()
  const tone = s === 'CONFIRMED' || !s ? 'green' : s === 'PENDING_APPROVAL' ? 'amber' : 'red'
  const Icon = tone === 'green' ? CheckCircle2 : tone === 'amber' ? Clock : XCircle
  return (
    <div className={cx('anim-in flex gap-2 rounded-xl px-3 py-2 text-[12.5px] leading-snug ring-1',
      tone === 'green' && 'bg-emerald-50 text-emerald-900 ring-emerald-200',
      tone === 'amber' && 'bg-amber-50 text-amber-900 ring-amber-200',
      tone === 'red' && 'bg-red-50 text-red-800 ring-red-200')}>
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span>{m.text}</span>
    </div>
  )
}

/** One run of the assistant's steps: only the current one while running, "✓ N steps" afterwards. */
function Steps({ items, running }: { items: Message[]; running: boolean }) {
  const [open, setOpen] = useState(false)
  if (running) {
    return (
      <div className="flex items-center gap-2 text-[12.5px] text-slate-500">
        <span className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-[#1f4fbf] border-r-transparent" />
        <span className="truncate">{items[items.length - 1].text}</span>
      </div>
    )
  }
  return (
    <div className="text-[12.5px] text-slate-500">
      <button type="button" onClick={() => setOpen(!open)} className="flex items-center gap-1.5 hover:text-slate-800">
        <span className="grid h-3.5 w-3.5 place-items-center rounded-full bg-emerald-500 text-white"><Check className="h-2.5 w-2.5" strokeWidth={3} /></span>
        {items.length} step{items.length === 1 ? '' : 's'}
        <ChevronDown className={cx('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <ol className="mt-1.5 space-y-1 border-l border-slate-200 pl-3 text-[12px] leading-snug">
          {items.map((m) => <li key={m.id}>{m.text}</li>)}
        </ol>
      )}
    </div>
  )
}

function Thinking() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map((d) => (
        <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#1f4fbf]/60" style={{ animationDelay: `${d * 140}ms` }} />
      ))}
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
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
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

  const iconBtn = 'grid h-9 w-9 shrink-0 place-items-center rounded-lg transition'

  return (
    <div className="shrink-0 border-t border-slate-200/80 px-4 py-3">
      <div className={cx('flex items-end gap-1.5 rounded-xl bg-white p-1.5 ring-1 transition',
        listening ? 'ring-2 ring-red-300' : 'ring-slate-200 focus-within:ring-2 focus-within:ring-[#1f4fbf]/40')}>
        <textarea ref={ta} rows={1} value={text} onChange={(e) => setText(e.target.value)} placeholder={listening ? 'Listening…' : placeholder}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit()
            }
          }}
          className="max-h-32 min-h-[36px] flex-1 resize-none border-0 bg-transparent px-2 py-2 text-[13.5px] text-slate-800 placeholder:text-slate-400 focus:outline-none" />
        {SRClass && (
          <button type="button" onClick={toggleMic} title={listening ? 'Stop listening' : 'Speak'}
            className={cx(iconBtn, listening ? 'live-mic bg-red-500 text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-[#0b2f6b]')}>
            {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          </button>
        )}
        <button type="button" onClick={submit} disabled={disabled || !text.trim()} title="Send"
          className={cx(iconBtn, 'bg-[#0b2f6b] text-white hover:bg-[#123d86] disabled:bg-slate-200 disabled:text-slate-400')}>
          <SendHorizontal className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
