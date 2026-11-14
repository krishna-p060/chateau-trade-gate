/** "Try to break it" tab: a rogue agent attacks the gate with no model or keys; each card shows the refusal and the audit rows. */
import { ArrowRight, KeyRound, Play, RotateCcw, ShieldCheck, ShieldX } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Spinner } from '../components/ToolSteps'
import { ActorIcon, cx, toneClasses } from '../components/ui'
import { actorKind } from '../lib/format'
import { cachedAttacks, loadAttacks, runAttack, useAttackRuns, type Attack, type AttackResult, type AttackRun, type DemoStatus, type Verdict } from './demo'
import { fNum, t, type Key } from './i18n'

const VERDICTS: Record<Verdict, Key> = {
  REFUSED: 'bi_v_refused', BLOCKED: 'bi_v_blocked', HELD: 'bi_v_held', DETECTED: 'bi_v_detected', NOT_STOPPED: 'bi_not_stopped',
}
const isStopped = (r: AttackResult) => r.stopped === true && r.verdict !== 'NOT_STOPPED'
const label = 'text-[11px] font-semibold uppercase tracking-wider text-slate-400'

export function NoKeyNotice({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-amber-200 bg-amber-50 px-5 py-2.5 text-[12.5px] leading-snug text-amber-900">
      <KeyRound className="h-4 w-4 shrink-0 text-amber-600" />
      <span className="min-w-0 flex-1 basis-48">
        <span className="font-semibold">{t('nokey_title')}</span> {t('nokey_body')}
      </span>
      <button type="button" onClick={onOpen}
        className="flex shrink-0 items-center gap-1.5 rounded-lg bg-[#0b2f6b] px-3 py-1.5 text-[12.5px] font-semibold text-white transition hover:bg-[#123d86]">
        {t('tab_break')} <ArrowRight className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

export function BreakIt({ status }: { status: DemoStatus | null }) {
  const [attacks, setAttacks] = useState<Attack[] | null>(cachedAttacks)
  const [err, setErr] = useState<string | null>(null)
  const [all, setAll] = useState(false)
  const runs = useAttackRuns()

  const load = useCallback(() => {
    loadAttacks().then((a) => {
      setAttacks(a)
      setErr(null)
    }).catch((e) => setErr(e instanceof Error ? e.message : String(e)))
  }, [])
  useEffect(load, [load])

  const runAll = async () => {
    setAll(true)
    for (const a of attacks || []) await runAttack(a.id)
    setAll(false)
  }

  const list = attacks || []
  const done = list.flatMap((a) => runs[a.id]?.result ?? [])
  const stopped = done.filter(isStopped).length
  const busy = all || list.some((a) => runs[a.id]?.busy)

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-slate-900">{t('bi_title')}</h1>
          <p className="mt-1 max-w-2xl text-[14px] text-slate-500">{t('bi_sub')}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {done.length > 0 && (
            <span className={cx('text-[13px] font-semibold tabular-nums', stopped === done.length ? 'text-emerald-700' : 'text-red-600')}>
              {t('bi_tally', { a: stopped, n: done.length })}
            </span>
          )}
          <button type="button" disabled={busy || list.length === 0} onClick={runAll}
            className="flex items-center gap-2 rounded-xl bg-[#0b2f6b] px-5 py-2.5 text-[14px] font-semibold text-white shadow-sm transition hover:bg-[#123d86] disabled:opacity-60">
            {all ? <Spinner /> : <Play className="h-4 w-4" />} {t('bi_run_all')}
          </button>
        </div>
      </div>
      {status?.demo && status.note && <p className="mt-3 max-w-2xl text-[12px] text-slate-400">{status.note}</p>}

      {err && !attacks && (
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-red-50 px-4 py-3 text-[13px] text-red-700 ring-1 ring-red-200">
          <span><span className="font-semibold">{t('bi_load_err')}.</span> {err}</span>
          <button type="button" onClick={load} className="rounded-lg bg-white px-3 py-1.5 font-semibold text-red-600 ring-1 ring-red-200 transition hover:bg-red-50">{t('try_again')}</button>
        </div>
      )}
      {!attacks && !err && <div className="mt-6 flex items-center gap-2 text-[13px] text-slate-500"><Spinner /> {t('loading')}</div>}

      <div className="mt-6 space-y-4">
        {list.map((a) => <AttackCard key={a.id} attack={a} run={runs[a.id]} locked={all} />)}
        {attacks && list.length === 0 && (
          <div className="rounded-2xl bg-white px-5 py-8 text-center text-[13px] text-slate-500 shadow-sm ring-1 ring-slate-200/80">{t('bi_empty')}</div>
        )}
      </div>

      <div className="mt-4 flex items-start gap-1.5 text-[11px] leading-snug text-slate-400">
        <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0" /> {t('bi_scratch')}
      </div>
    </div>
  )
}

function AttackCard({ attack, run, locked }: { attack: Attack; run?: AttackRun; locked: boolean }) {
  const r = run?.result
  const busy = !!run?.busy
  const ok = r ? isStopped(r) : true
  return (
    <div className={cx('overflow-hidden rounded-2xl bg-white shadow-sm ring-1', ok ? 'ring-slate-200/80' : 'ring-red-300')}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 px-5 py-4 sm:px-6">
        <div className="min-w-0 flex-1 basis-64">
          <div className="text-[16px] font-semibold text-slate-900">{attack.title}</div>
          <p className="mt-0.5 text-[13px] leading-snug text-slate-500">{attack.attempt}</p>
        </div>
        <button type="button" disabled={busy || locked} onClick={() => runAttack(attack.id)}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-white px-3.5 py-2 text-[13px] font-semibold text-[#0b2f6b] ring-1 ring-slate-200 transition hover:bg-[#eef3fc] disabled:opacity-60">
          {busy ? <Spinner /> : r ? <RotateCcw className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          {busy ? t('bi_running') : r ? t('bi_again') : t('bi_run')}
        </button>
      </div>

      {run?.error && (
        <div className="mx-5 mb-4 rounded-xl bg-red-50 px-4 py-3 text-[13px] text-red-700 ring-1 ring-red-200 sm:mx-6">
          <span className="font-semibold">{t('bi_run_err')}.</span> {run.error.message}
          <span className="ml-2 font-mono text-[11.5px] text-red-500">{run.error.code}</span>
        </div>
      )}

      {r && (
        <div className={cx('anim-in border-t border-slate-100 transition-opacity', busy && 'opacity-50')}>
          <div className="grid gap-x-6 gap-y-4 px-5 py-4 sm:px-6 md:grid-cols-5">
            <div className="min-w-0 md:col-span-2">
              <div className={cx(label, 'mb-2')}>{t('bi_steps')}</div>
              <ol className="space-y-1.5">
                {r.steps.map((s, i) => (
                  <li key={i} className="flex gap-2 text-[12.5px] leading-snug text-slate-700">
                    <span className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-slate-100 text-[10.5px] font-semibold tabular-nums text-slate-500">{i + 1}</span>
                    <span className="min-w-0 break-words">{s}</span>
                  </li>
                ))}
              </ol>
            </div>
            <div className="min-w-0 md:col-span-3">
              <div className={cx(label, 'mb-2')}>{t('bi_answer')}</div>
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset', toneClasses[ok ? 'green' : 'red'])}>
                  {ok ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldX className="h-3.5 w-3.5" />}
                  {ok ? t('bi_stopped') : t('bi_not_stopped')}
                </span>
                {ok && <span className="text-[12.5px] font-medium text-slate-600">{VERDICTS[r.verdict] ? t(VERDICTS[r.verdict]) : r.verdict}</span>}
                <span className="ml-auto text-[11.5px] tabular-nums text-slate-400">{t('bi_ms', { n: fNum(Math.round(r.ms)) })}</span>
              </div>
              {r.code && <div className="mt-2 break-all font-mono text-[12px] text-slate-700">{r.code}</div>}
              <p className={cx('mt-1 text-[13px] leading-snug', ok ? 'text-slate-700' : 'text-red-700')}>{r.message}</p>
            </div>
          </div>

          <div className="border-t border-slate-100 bg-slate-50/70 px-5 py-3.5 sm:px-6">
            <div className={cx(label, 'mb-2')}>{t('bi_audit')}</div>
            {r.audit.length === 0 && <div className="text-[12.5px] text-slate-500">{t('bi_no_audit')}</div>}
            <div className="space-y-2">
              {r.audit.map((row) => (
                <div key={row.seq} className="flex items-start gap-2.5 text-[12.5px] leading-snug">
                  <span className="w-9 shrink-0 pt-1.5 text-right font-mono text-[11px] tabular-nums text-slate-400">#{row.seq}</span>
                  <ActorIcon actor={row.actor} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                      <span className="min-w-0 break-all font-medium text-slate-800" title={row.actor}>{actorKind(row.actor).name}</span>
                      <span className="shrink-0 font-mono text-[11px] text-slate-400" title={row.hash}>{row.hash.slice(0, 10)}</span>
                    </div>
                    <div className="break-words text-slate-600">{row.summary}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
