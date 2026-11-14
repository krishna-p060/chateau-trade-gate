import { ArrowRight, Bell, Bot, CheckCircle2, Clock, Euro, Heart, Link2, Receipt, Repeat, SearchX, ShieldCheck, ShieldX, Sparkles, XCircle } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { cx } from '../components/ui'
import { fAgo as ago, fDay as day, fEur as eur, fNum as num, fUnit, t, type Key } from './i18n'
import type { AuditEntry } from '../types'
import { shop, type Insights } from './api'
import type { Customer } from './types'

interface SignalData {
  from?: { product_id?: string; name?: string }
  to?: { product_id?: string; name?: string }
  order_id?: string
  suggested?: string
  chosen?: string
  need?: string
  option_rank?: number
  product?: { product_id?: string; name?: string }
  quantity?: number
  unit?: string
  deliver_by?: string
}

export function ValioView({ customers }: { customers: Customer[] }) {
  const [data, setData] = useState<Insights | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const load = () => shop.insights().then((d) => { if (alive) { setData(d); setErr(null) } }).catch((e) => alive && setErr(String(e?.message || e)))
    load()
    const id = window.setInterval(load, 5000)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [])

  const name = (id: string | null | undefined) => customers.find((c) => c.id === id)?.name || id || '—'
  const signals = data?.signals || []
  const orders = data?.orders || []
  const subs = signals.filter((s) => s.event === 'signal.substitution').length
  const notifies = signals.filter((s) => s.event === 'signal.notify').length
  const unmet = signals.filter((s) => s.event === 'signal.unmet').length
  const confirmed = orders.filter((o) => o.status === 'CONFIRMED')
  const total = confirmed.reduce((s, o) => s + (o.total || 0), 0)
  const viaShop = orders.filter((o) => (o.rationale || '').includes('Aimo Assistant')).length
  const integ = data?.integrity
  const intact = integ ? (integ.valid ?? integ.ok ?? false) : null
  const checked = integ?.checked ?? integ?.entries

  return (
    <div className="mx-auto w-full max-w-6xl px-8 py-8">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wider text-[#1f4fbf]">{t('vv_kicker')}</div>
        <h1 className="mt-0.5 text-2xl font-semibold text-slate-900">{t('vv_title')}</h1>
        <p className="mt-1 max-w-3xl text-[14px] text-slate-500">
          {t('vv_sub')}
        </p>
      </div>
      {err && !data && <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-[13px] text-red-700 ring-1 ring-red-200">{err}</div>}

      <div className="mt-6 grid grid-cols-4 gap-4">
        <Tile icon={<Receipt className="h-4 w-4" />} label={t('kpi_orders')} value={String(orders.length)} sub={t('kpi_via', { n: viaShop })} />
        <Tile icon={<Euro className="h-4 w-4" />} label={t('kpi_value')} value={eur(total, true)} sub={t('kpi_confirmed', { n: confirmed.length })} />
        <Tile icon={<Repeat className="h-4 w-4" />} label={t('kpi_subs')} value={String(subs)} sub={t('kpi_subs_sub', { a: notifies, b: unmet })} />
        <Tile icon={intact === false ? <ShieldX className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />} label={t('kpi_audit')}
          value={intact === null ? '—' : intact ? t('chain_ok') : t('chain_broken')}
          valueClass={intact === false ? 'text-red-600' : 'text-emerald-700'}
          sub={intact === null ? '' : `${t('chain_n', { n: checked ?? '?' })} ${intact ? '✓' : '✗'}`} />
      </div>

      <div className="mt-6 grid grid-cols-5 gap-6">
        <section className="col-span-2">
          <SectionHead icon={<Sparkles className="h-4 w-4" />} title={t('signals')} />
          <div className="space-y-2.5">
            {signals.map((s) => <SignalCard key={s.seq} s={s} name={name(s.buyer_id)} />)}
            {signals.length === 0 && (
              <div className="rounded-2xl bg-white px-5 py-8 text-center text-[13px] text-slate-500 shadow-sm ring-1 ring-slate-200/80">
                {t('signals_empty')}
              </div>
            )}
          </div>
        </section>

        <section className="col-span-3">
          <SectionHead icon={<Receipt className="h-4 w-4" />} title={t('recent_orders')} />
          <div className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200/80">
            <table className="w-full text-left text-[13px]">
              <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-4 py-2.5">{t('th_customer')}</th>
                  <th className="px-4 py-2.5">{t('th_channel')}</th>
                  <th className="px-4 py-2.5">{t('th_status')}</th>
                  <th className="px-4 py-2.5 text-right">{t('th_total')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {orders.slice(0, 14).map((o) => {
                  const shopOrder = (o.rationale || '').includes('Aimo Assistant')
                  return (
                    <tr key={o.id} className="transition hover:bg-slate-50/70">
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-slate-800">{name(o.buyer_id)}</div>
                        <div className="text-[11.5px] text-slate-400"><span className="font-mono">{o.id}</span> · {ago(o.updated || o.created)}</div>
                      </td>
                      <td className="px-4 py-2.5">
                        {shopOrder
                          ? <span className="inline-flex items-center gap-1 rounded-full bg-[#eef3fc] px-2 py-0.5 text-[11.5px] font-medium text-[#0b2f6b]"><Sparkles className="h-3 w-3" />{t('ch_shop')}</span>
                          : <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11.5px] font-medium text-slate-600"><Bot className="h-3 w-3" />{t('ch_api')}</span>}
                      </td>
                      <td className="px-4 py-2.5"><Status s={o.status} /></td>
                      <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-slate-900">{eur(o.total)}</td>
                    </tr>
                  )
                })}
                {orders.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">{t('no_orders')}</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
}

function Tile({ icon, label, value, sub, valueClass }: { icon: ReactNode; label: string; value: string; sub?: string; valueClass?: string }) {
  return (
    <div className="rounded-2xl bg-white px-5 py-4 shadow-sm ring-1 ring-slate-200/80">
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-slate-500"><span className="text-[#1f4fbf]">{icon}</span>{label}</div>
      <div className={cx('mt-1.5 text-[26px] font-semibold leading-tight tabular-nums text-slate-900', valueClass)}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-slate-400">{sub}</div>}
    </div>
  )
}

function SectionHead({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-slate-500">
      <span className="text-[#1f4fbf]">{icon}</span>{title}
    </div>
  )
}

const KINDS: Record<string, { label: Key; icon: typeof Repeat; cls: string }> = {
  'signal.substitution': { label: 'sig_sub', icon: Repeat, cls: 'bg-amber-50 text-amber-800' },
  'signal.preference': { label: 'sig_pref', icon: Heart, cls: 'bg-[#eef3fc] text-[#0b2f6b]' },
  'signal.notify': { label: 'sig_notify', icon: Bell, cls: 'bg-sky-50 text-sky-800' },
  'signal.unmet': { label: 'sig_unmet', icon: SearchX, cls: 'bg-red-50 text-red-700' },
}

function Status({ s }: { s: string }) {
  const u = (s || '').toUpperCase()
  const [label, cls, Icon] = u === 'CONFIRMED' ? [t('st_confirmed'), 'bg-emerald-50 text-emerald-700 ring-emerald-600/20', CheckCircle2]
    : u === 'PENDING_APPROVAL' ? [t('st_pending'), 'bg-amber-50 text-amber-800 ring-amber-600/25', Clock]
      : u === 'REJECTED' ? [t('st_rejected'), 'bg-red-50 text-red-700 ring-red-600/20', XCircle]
        : [s, 'bg-slate-100 text-slate-600 ring-slate-500/20', Clock]
  return (
    <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset', cls)}>
      <Icon className="h-3.5 w-3.5" />{label}
    </span>
  )
}

function SignalCard({ s, name }: { s: AuditEntry; name: string }) {
  const d = (s.data || {}) as SignalData
  const kind = KINDS[s.event]
  const k = { label: kind ? t(kind.label) : s.event.replace('signal.', ''), icon: kind?.icon || Sparkles, cls: kind?.cls || 'bg-slate-100 text-slate-600' }
  const Icon = k.icon
  let body: ReactNode
  if (s.event === 'signal.substitution' && d.from && d.to) {
    body = (
      <div className="mt-2 space-y-0.5 text-[12.5px] leading-snug">
        <div className="text-slate-400 line-through decoration-slate-300">{d.from.name}</div>
        <div className="flex items-start gap-1.5 font-medium text-slate-800">
          <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />{d.to.name}
        </div>
      </div>
    )
  } else if (s.event === 'signal.notify' && d.product?.name) {
    body = (
      <div className="mt-1.5 text-[12.5px] leading-snug">
        <div className="font-medium text-slate-800">{d.product.name}</div>
        <div className="text-slate-500">{t('sig_notify_body')}</div>
      </div>
    )
  } else if (s.event === 'signal.unmet' && d.need) {
    body = (
      <div className="mt-1.5 text-[12.5px] leading-snug">
        <div className="font-medium text-slate-800">{d.need}</div>
        <div className="text-slate-500">
          {typeof d.quantity === 'number' && <>{num(d.quantity)} {fUnit(d.unit)} </>}
          {d.deliver_by && <>{t('needed_by', { d: day(d.deliver_by) })} </>}– {t('sig_unmet_body')}
        </div>
      </div>
    )
  } else {
    body = (
      <div className="mt-1.5 text-[12.5px] leading-snug text-slate-700">
        {d.need && <div className="font-medium text-slate-800">{d.need}</div>}
        <div className="text-slate-500">{s.summary}</div>
      </div>
    )
  }
  return (
    <div className="anim-in rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200/80">
      <div className="flex items-center gap-2 text-[11.5px]">
        <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold', k.cls)}>
          <Icon className="h-3 w-3" />{k.label}
        </span>
        <span className="truncate text-slate-500">{name}</span>
        <span className="ml-auto shrink-0 text-slate-400">{ago(s.ts)}</span>
      </div>
      {body}
      {d.order_id && <div className="mt-1.5 flex items-center gap-1 font-mono text-[10.5px] text-slate-400"><Link2 className="h-3 w-3" />{d.order_id}</div>}
    </div>
  )
}
