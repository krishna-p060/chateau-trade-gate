import { BookOpen, FileSignature, Plus, Save, ShieldAlert, Trash2, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Spinner } from '../components/ToolSteps'
import { cx } from '../components/ui'
import type { SettingsIn } from './api'
import { fUnit, t } from './i18n'
import type { Customer } from './types'

interface Props {
  customer: Customer
  onSave: (body: SettingsIn) => Promise<boolean>
}

/** Keyed by customer id from the parent, so switching customer resets the form. */
export function Preferences({ customer, onSave }: Props) {
  const [priorities, setPriorities] = useState<string[]>(customer.priorities || [])
  const [allergens, setAllergens] = useState<string[]>(customer.rules?.avoid_allergens || [])
  const [newAllergen, setNewAllergen] = useState('')
  const [limit, setLimit] = useState<string>(customer.approval_limit_eur != null ? String(customer.approval_limit_eur) : '')
  const [auto, setAuto] = useState(!!customer.settings?.auto_confirm_standing_orders)
  const [reminder, setReminder] = useState<string>(customer.settings?.reminder || 'sms')
  const [saving, setSaving] = useState(false)
  const approver = customer.approvers?.[0] || t('your_approver')

  const addAllergen = () => {
    const a = newAllergen.trim().toLowerCase()
    if (a && !allergens.includes(a)) setAllergens([...allergens, a])
    setNewAllergen('')
  }

  const save = async () => {
    setSaving(true)
    await onSave({
      priorities: priorities.map((p) => p.trim()).filter(Boolean),
      avoid_allergens: allergens,
      approval_limit_eur: limit.trim() === '' ? null : Number(limit),
      auto_confirm_standing_orders: auto,
      reminder,
    })
    setSaving(false)
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-8 py-8">
      <h1 className="text-2xl font-semibold text-slate-900">{t('prefs_title')}</h1>
      <p className="mt-1 text-[14px] text-slate-500">{t('prefs_for', { name: customer.name })}</p>
      <div className="mt-4 flex gap-3 rounded-xl bg-[#eef3fc] px-4 py-3 text-[13px] leading-relaxed text-[#0b2f6b]">
        <FileSignature className="mt-0.5 h-4.5 w-4.5 shrink-0" />
        <span>{t('prefs_explainer')}</span>
      </div>

      <div className="mt-6 space-y-5">
        <Section title={t('prio_title')} hint={t('prio_hint')}>
          <div className="space-y-2">
            {priorities.map((p, i) => (
              <div key={i} className="group flex items-center gap-2">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-slate-100 text-[11.5px] font-semibold text-slate-500">{i + 1}</span>
                <input value={p} onChange={(e) => setPriorities(priorities.map((x, j) => (j === i ? e.target.value : x)))}
                  className="min-w-0 flex-1 rounded-lg border-0 bg-white px-3 py-2 text-[13.5px] text-slate-800 ring-1 ring-slate-200 focus:ring-2 focus:ring-[#1f4fbf]/40 focus:outline-none" />
                <button type="button" title={t('remove')} onClick={() => setPriorities(priorities.filter((_, j) => j !== i))}
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-300 transition hover:bg-red-50 hover:text-red-500">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            <button type="button" onClick={() => setPriorities([...priorities, ''])}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[13px] font-medium text-[#1f4fbf] transition hover:bg-[#eef3fc]">
              <Plus className="h-4 w-4" /> {t('add_priority')}
            </button>
          </div>
        </Section>

        <Section title={t('allergens_title')} hint={t('allergens_hint')}>
          <div className="flex flex-wrap items-center gap-2">
            {allergens.map((a) => (
              <span key={a} className="inline-flex items-center gap-1 rounded-full bg-red-50 py-1 pl-3 pr-1.5 text-[13px] font-medium text-red-700 ring-1 ring-red-200">
                <ShieldAlert className="h-3.5 w-3.5" />{a}
                <button type="button" title={t('remove_x', { x: a })} onClick={() => setAllergens(allergens.filter((x) => x !== a))}
                  className="grid h-5 w-5 place-items-center rounded-full hover:bg-red-100"><X className="h-3 w-3" /></button>
              </span>
            ))}
            {allergens.length === 0 && <span className="text-[13px] text-slate-400">{t('none')}</span>}
            <div className="flex items-center gap-1">
              <input value={newAllergen} onChange={(e) => setNewAllergen(e.target.value)} placeholder={t('allergen_ph')}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addAllergen() } }}
                className="w-36 rounded-lg border-0 bg-white px-3 py-1.5 text-[13px] ring-1 ring-slate-200 focus:ring-2 focus:ring-[#1f4fbf]/40 focus:outline-none" />
              <button type="button" onClick={addAllergen} className="grid h-8 w-8 place-items-center rounded-lg text-[#1f4fbf] hover:bg-[#eef3fc]"><Plus className="h-4 w-4" /></button>
            </div>
          </div>
        </Section>

        <Section title={t('limit_title')} hint={t('limit_hint', { who: approver })}>
          <div className="flex items-center gap-2">
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[14px] text-slate-400">€</span>
              <input type="number" min={0} step={100} value={limit} onChange={(e) => setLimit(e.target.value)}
                className="w-44 rounded-lg border-0 bg-white py-2 pl-7 pr-3 text-[14px] font-medium tabular-nums text-slate-800 ring-1 ring-slate-200 focus:ring-2 focus:ring-[#1f4fbf]/40 focus:outline-none" />
            </div>
            <span className="text-[13px] text-slate-500">{t('per_order')}</span>
          </div>
        </Section>

        <Section title={t('templates_title')}>
          <label className="flex cursor-pointer items-center justify-between gap-4">
            <span className="text-[13.5px] text-slate-700">{t('auto_confirm')}</span>
            <button type="button" role="switch" aria-checked={auto} onClick={() => setAuto(!auto)}
              className={cx('relative h-6 w-11 shrink-0 rounded-full transition', auto ? 'bg-emerald-500' : 'bg-slate-300')}>
              <span className={cx('absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all', auto ? 'left-[22px]' : 'left-0.5')} />
            </button>
          </label>
          <div className="mt-4 flex items-center justify-between gap-4 border-t border-slate-100 pt-4">
            <span className="text-[13.5px] text-slate-700">{t('reminder_label')}</span>
            <div role="group" aria-label={t('reminder_title')} className="flex shrink-0 rounded-lg bg-slate-100 p-0.5 text-[12.5px] font-semibold">
              {(['sms', 'email', 'off'] as const).map((c) => (
                <button key={c} type="button" aria-pressed={reminder === c} onClick={() => setReminder(c)}
                  className={cx('rounded-md px-2.5 py-1 transition', reminder === c ? 'bg-white text-[#0b2f6b] shadow-sm' : 'text-slate-500 hover:text-slate-800')}>
                  {t(c === 'sms' ? 'rem_sms' : c === 'email' ? 'rem_email' : 'rem_off')}
                </button>
              ))}
            </div>
          </div>
        </Section>
      </div>

      <div className="mt-6 flex justify-end">
        <button type="button" onClick={save} disabled={saving}
          className="flex items-center gap-2 rounded-xl bg-[#0b2f6b] px-5 py-2.5 text-[14px] font-semibold text-white shadow-sm transition hover:bg-[#123d86] disabled:opacity-60">
          {saving ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />} {t('save_prefs')}
        </button>
      </div>

      <div className="mt-8"><Recipes customer={customer} /></div>
    </div>
  )
}

function Recipes({ customer }: { customer: Customer }) {
  const recipes = customer.recipes || []
  return (
    <Section title={t('recipes_title')} hint={t('recipes_hint')}>
      {recipes.length === 0 && <div className="text-[13px] text-slate-400">{t('no_recipes')}</div>}
      <div className="space-y-3">
        {recipes.map((r) => (
          <div key={r.id} className="rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
            <div className="flex items-baseline gap-2">
              <BookOpen className="h-3.5 w-3.5 translate-y-0.5 text-[#1f4fbf]" />
              <span className="text-[14px] font-semibold text-slate-800">{r.name}</span>
              {r.portions != null && <span className="text-[12.5px] text-slate-500">{t('portions_n', { n: r.portions })}</span>}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px] text-slate-600">
              {(r.ingredients || []).map((i, n) => (
                <span key={n}>{i.name} <span className="font-medium tabular-nums text-slate-800">{i.quantity} {fUnit(i.unit)}</span></span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl bg-white px-5 py-4 shadow-sm ring-1 ring-slate-200/80">
      <div className="mb-3">
        <div className="text-[14.5px] font-semibold text-slate-900">{title}</div>
        {hint && <div className="text-[12.5px] text-slate-500">{hint}</div>}
      </div>
      {children}
    </section>
  )
}
