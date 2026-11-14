import { AlertCircle, ArrowRight, CalendarClock, Check, ChevronRight, MessageSquareText, RotateCcw, ShieldCheck } from 'lucide-react'
import { Fragment, useState } from 'react'
import { Spinner } from '../components/ToolSteps'
import { cx } from '../components/ui'
import { num } from '../lib/format'
import { OrderView, Products, type CartActions } from './Cart'
import { Ingredients, PlanList } from './Ingredients'
import type { Customer, Funnel, PlanItemOut, Question, Session } from './types'

interface Props extends CartActions {
  session: Session | null
  customer: Customer | null
  sending: boolean
  onSend: (text: string) => void
  onStanding: (id: string) => void
  onAnswers: (answers: Record<string, string>) => Promise<void>
  onApprove: (items: PlanItemOut[], save: string[]) => Promise<void>
  onNew: () => void
}

/** The guided workspace: a stepper and exactly one thing to look at for the current state. */
export function Workspace(p: Props) {
  const { session, customer, sending } = p
  const busy = !!session?.busy || sending
  const order = session?.order ?? null
  const cart = session?.cart?.lines?.length ? session.cart : null
  const plan = session?.plan ?? null
  const questions = session?.question?.questions || []
  const actions: CartActions = p

  let step = order ? 3 : cart ? 2 : plan ? 1 : 0
  let body
  if (order) {
    body = <OrderView cart={cart} order={order} onSaveTemplate={p.onSaveTemplate} onNew={p.onNew} />
  } else if (questions.length && !busy) {
    body = <Questions key={questions.map((q) => q.id + q.text).join('|')} questions={questions} onAnswers={p.onAnswers} />
  } else if (cart) {
    body = (
      <div className="flex h-full min-h-0 flex-col">
        {busy && session?.status !== 'ordering' && <WorkingBar session={session} />}
        <div className="min-h-0 flex-1"><Products cart={cart} plan={plan} busy={busy} actions={actions} /></div>
      </div>
    )
  } else if (plan && plan.status === 'proposed' && !busy) {
    body = <Ingredients key={plan.items.map((i) => `${i.key}:${i.quantity}${i.unit}`).join('|')} plan={plan} onApprove={p.onApprove} />
  } else if (plan) {
    if (plan.status === 'approved') step = 2
    body = (
      <div className="flex h-full min-h-0 flex-col">
        {busy ? <WorkingBar session={session} /> : <StalledBar session={session} onRetry={() => p.onSend('Please try again.')} />}
        <div className={cx('min-h-0 flex-1 overflow-y-auto px-8 py-5', busy && 'opacity-50')}><PlanList plan={plan} /></div>
      </div>
    )
  } else if (busy) {
    body = <Working session={session} />
  } else {
    body = <Start customer={customer} onSend={p.onSend} onStanding={p.onStanding} />
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Stepper current={step} done={order?.status === 'CONFIRMED'} skippedIngredients={!plan && (!!cart || !!order)} />
      <div className="min-h-0 flex-1">{body}</div>
    </div>
  )
}

// ------------------------------------------------------------------ stepper
const STEPS = ['Request', 'Ingredients', 'Products', 'Order']

function Stepper({ current, done, skippedIngredients }: { current: number; done: boolean; skippedIngredients: boolean }) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-2 border-b border-slate-200/80 bg-white px-8">
      {STEPS.map((label, i) => {
        const isDone = i < current || (done && i === current)
        const active = i === current && !done
        const skipped = i === 1 && skippedIngredients
        return (
          <Fragment key={label}>
            {i > 0 && <ChevronRight className="h-4 w-4 shrink-0 text-slate-300" />}
            <div className={cx('flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-[13px] font-medium transition',
              active ? 'bg-[#eef3fc] text-[#0b2f6b]' : isDone ? 'text-slate-700' : 'text-slate-400')}>
              <span className={cx('grid h-6 w-6 place-items-center rounded-full text-[12px] font-semibold',
                active ? 'bg-[#0b2f6b] text-white' : skipped ? 'bg-slate-100 text-slate-400' : isDone ? 'bg-emerald-500 text-white' : 'bg-slate-100 text-slate-400')}>
                {skipped ? '–' : isDone ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
              </span>
              {skipped ? 'Your list' : label}
            </div>
          </Fragment>
        )
      })}
      <span className="ml-auto flex items-center gap-1.5 text-[12px] text-slate-400">
        <ShieldCheck className="h-3.5 w-3.5" />You approve every step
      </span>
    </div>
  )
}

// ------------------------------------------------------------------ start
function Start({ customer, onSend, onStanding }: { customer: Customer | null; onSend: (t: string) => void; onStanding: (id: string) => void }) {
  const sugg = customer?.suggestions || []
  const templates = customer?.standing_orders || []
  return (
    <div className="h-full overflow-y-auto"><div className="flex min-h-full items-center justify-center px-8 py-6">
      <div className="w-full max-w-xl">
        <h1 className="text-center text-[26px] font-semibold text-slate-900">What are you cooking?</h1>
        <p className="mt-1.5 text-center text-[13.5px] text-slate-500">You approve every step. Nothing is ordered until you confirm.</p>

        <div className="mt-6 space-y-2">
          {sugg.map((s) => (
            <button key={s} type="button" onClick={() => onSend(s)}
              className="group flex w-full items-center gap-3 rounded-xl bg-white px-4 py-3 text-left text-[14.5px] font-medium text-slate-800 ring-1 ring-slate-200 transition hover:ring-2 hover:ring-[#1f4fbf]/50">
              <span className="min-w-0 flex-1">{s}</span>
              <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-[#1f4fbf]" />
            </button>
          ))}
        </div>

        {templates.length > 0 && (
          <div className="mt-6">
            <div className="mb-2 text-[12px] font-semibold uppercase tracking-wider text-slate-400">Your order templates</div>
            <div className="space-y-2">
              {templates.slice(0, 3).map((t) => (
                <div key={t.id} className="flex items-center gap-3 rounded-xl bg-white px-4 py-2.5 ring-1 ring-slate-200">
                  <CalendarClock className="h-5 w-5 shrink-0 text-[#0b2f6b]/70" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14px] font-medium text-slate-800">{t.name}</div>
                    <div className="text-[12px] text-slate-500">{t.lines.length} items · {t.weekdays.map((d) => d.slice(0, 3)).join('/')}</div>
                  </div>
                  <button type="button" onClick={() => onStanding(t.id)}
                    className="shrink-0 rounded-lg px-3 py-1.5 text-[13px] font-semibold text-[#0b2f6b] ring-1 ring-slate-200 transition hover:bg-[#eef3fc]">
                    Check for next delivery
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="mt-5 flex items-center justify-center gap-1.5 text-[12.5px] text-slate-400">
          <MessageSquareText className="h-3.5 w-3.5" />or type or speak your own request on the left
        </p>
      </div>
    </div></div>
  )
}

// ------------------------------------------------------------------ questions
function Questions({ questions, onAnswers }: { questions: Question[]; onAnswers: (a: Record<string, string>) => Promise<void> }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const single = questions.length === 1
  const all = questions.every((q) => answers[q.id])

  const submit = async (a: Record<string, string>) => {
    setBusy(true)
    await onAnswers(a)
    setBusy(false)
  }
  const pick = (q: Question, o: string) => {
    if (busy) return
    const next = { ...answers, [q.id]: o }
    setAnswers(next)
    if (single) void submit(next)
  }

  return (
    <div className="h-full overflow-y-auto"><div className="flex min-h-full items-center justify-center px-8 py-6">
      <div className="w-full max-w-xl rounded-2xl bg-white px-7 py-6 shadow-sm ring-1 ring-slate-200">
        <div className="text-[12px] font-semibold uppercase tracking-wider text-[#1f4fbf]">Quick question{single ? '' : 's'}</div>
        <div className="mt-3 space-y-5">
          {questions.map((q) => (
            <div key={q.id}>
              <div className="text-[16px] font-semibold text-slate-900">{q.text}</div>
              <div className="mt-2.5 flex flex-wrap gap-2">
                {q.options.map((o) => {
                  const on = answers[q.id] === o
                  return (
                    <button key={o} type="button" disabled={busy} onClick={() => pick(q, o)}
                      className={cx('rounded-xl px-4 py-2.5 text-[14px] font-medium ring-1 transition',
                        on ? 'bg-[#0b2f6b] text-white ring-[#0b2f6b]' : 'bg-white text-slate-800 ring-slate-300 hover:bg-[#eef3fc] hover:ring-[#1f4fbf]/50')}>
                      {o}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-6 flex items-center gap-4">
          <span className="text-[12.5px] text-slate-400">or type your answer on the left</span>
          {!single && (
            <button type="button" disabled={!all || busy} onClick={() => submit(answers)}
              className="ml-auto flex items-center gap-2 rounded-xl bg-[#0b2f6b] px-5 py-2.5 text-[14px] font-semibold text-white transition hover:bg-[#123d86] disabled:bg-slate-300">
              {busy && <Spinner className="h-4 w-4" />}Continue<ArrowRight className="h-4 w-4" />
            </button>
          )}
          {single && busy && <Spinner className="ml-auto h-4 w-4 text-[#1f4fbf]" />}
        </div>
      </div>
    </div></div>
  )
}

// ------------------------------------------------------------------ working
function progressOf(session: Session | null): { text: string; funnel: Funnel | null } {
  const msgs = session?.messages || []
  const from = msgs.map((m) => m.role).lastIndexOf('user')
  const run = msgs.slice(from + 1).filter((m) => m.role === 'progress')
  const last = run[run.length - 1]
  const funnel = [...run].reverse().find((m) => m.funnel)?.funnel ?? null
  const fallback = session?.plan?.status === 'revising' ? 'Updating the list…' : 'Working on it…'
  return { text: last?.funnel ? 'Checking live price and stock…' : last?.text || fallback, funnel }
}

function FunnelView({ f }: { f: Funnel }) {
  const parts: [number | undefined, string][] = [[f.catalog_size, 'products'], [f.checked_live, 'checked live'], [f.shortlisted, 'candidates']]
  return (
    <div className="flex items-center gap-3">
      {parts.filter(([n]) => typeof n === 'number').map(([n, label], i) => (
        <Fragment key={label}>
          {i > 0 && <ArrowRight className="h-4 w-4 text-slate-300" />}
          <span className="text-[13px] text-slate-500"><span className="text-[17px] font-semibold tabular-nums text-slate-900">{num(n)}</span> {label}</span>
        </Fragment>
      ))}
    </div>
  )
}

function Working({ session }: { session: Session | null }) {
  const { text, funnel } = progressOf(session)
  return (
    <div className="grid h-full place-items-center px-8">
      <div className="flex flex-col items-center gap-4 text-center">
        <Spinner className="h-8 w-8 border-[3px] text-[#1f4fbf]" />
        <div className="text-[16px] font-medium text-slate-800">{text}</div>
        {funnel && <FunnelView f={funnel} />}
      </div>
    </div>
  )
}

/** The run stopped without a result (an error, or the assistant only replied in the chat). */
function StalledBar({ session, onRetry }: { session: Session | null; onRetry: () => void }) {
  const msgs = session?.messages || []
  const failed = msgs[msgs.length - 1]?.role === 'error'
  return (
    <div className={cx('flex shrink-0 items-center gap-3 border-b px-8 py-2.5 text-[13.5px] font-medium',
      failed ? 'border-red-200 bg-red-50 text-red-800' : 'border-amber-200 bg-amber-50 text-amber-900')}>
      <AlertCircle className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">
        {failed ? 'Something went wrong while finding products. Your approved list is safe.' : 'Aimo replied in the chat — nothing was ordered.'}
      </span>
      <button type="button" onClick={onRetry}
        className="flex shrink-0 items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-[13px] font-semibold text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50">
        <RotateCcw className="h-3.5 w-3.5" />Try again
      </button>
    </div>
  )
}

function WorkingBar({ session }: { session: Session | null }) {
  const { text, funnel } = progressOf(session)
  return (
    <div className="flex shrink-0 items-center gap-4 border-b border-[#d9e4f8] bg-[#eef3fc] px-8 py-2.5">
      <Spinner className="h-4 w-4 shrink-0 text-[#1f4fbf]" />
      <span className="truncate text-[13.5px] font-medium text-[#0b2f6b]">{text}</span>
      {funnel && <div className="ml-auto shrink-0"><FunnelView f={funnel} /></div>}
    </div>
  )
}
