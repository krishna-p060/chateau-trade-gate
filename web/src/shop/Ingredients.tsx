import { ArrowRight, BookOpen, Check, Minus, Plus, Sparkles, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { Spinner } from '../components/ToolSteps'
import { cx } from '../components/ui'
import { fDay, fNum, fUnit, getLang, t, tn } from './i18n'
import type { Plan, PlanDish, PlanItem, PlanItemOut } from './types'

const UNITS = ['kg', 'l', 'pcs']
const OTHER = '__other__'

interface Row {
  id: number
  key: string | null
  name: string
  qty: string
  unit: string
  dish: string | null
  orig: PlanItem | null
}

const toNum = (s: string) => {
  const n = Number(String(s).replace(',', '.'))
  return Number.isFinite(n) ? n : 0
}
const fmt = (n: number) => {
  const s = String(Math.round(n * 100) / 100)
  return getLang() === 'fi' ? s.replace('.', ',') : s
}

function changed(r: Row): boolean {
  if (!r.orig) return true
  return r.orig.edited === true || r.name.trim() !== r.orig.name || toNum(r.qty) !== r.orig.quantity || r.unit !== r.orig.unit
}

function groupsOf<T extends { dish?: string | null }>(dishes: PlanDish[], items: T[]) {
  const names = new Set(dishes.map((d) => d.name))
  const out: { id: string; dish: PlanDish | null; items: T[] }[] = dishes.map((d) => ({ id: d.name, dish: d, items: items.filter((i) => i.dish === d.name) }))
  const rest = items.filter((i) => !i.dish || !names.has(i.dish))
  if (rest.length || !dishes.length) out.push({ id: OTHER, dish: null, items: rest })
  return out
}

function DishHead({ dish, save, onSave }: { dish: PlanDish | null; save?: boolean; onSave?: (v: boolean) => void }) {
  if (!dish) return <div className="text-[13px] font-semibold text-slate-700">{t('other')}</div>
  const recipe = dish.source === 'recipe'
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
      <span className="text-[14.5px] font-semibold text-slate-900">{dish.name}</span>
      {dish.portions != null && <span className="text-[12.5px] text-slate-500">{t('portions_n', { n: fNum(dish.portions) })}</span>}
      {recipe || dish.saved ? null : (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11.5px] font-medium text-amber-800">
          <Sparkles className="h-3 w-3" />{t('estimate')}
        </span>
      )}
      {recipe && (
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11.5px] font-medium text-emerald-700">
          <BookOpen className="h-3 w-3" />
          {t('from_recipe')}{dish.recipe_name ? ` “${dish.recipe_name}”` : ''}
          {dish.recipe_portions != null && dish.portions != null && dish.recipe_portions !== dish.portions
            && <> · {t('scaled', { a: fNum(dish.recipe_portions), b: fNum(dish.portions) })}</>}
        </span>
      )}
      {!recipe && (dish.saved
        ? <span className="flex items-center gap-1 text-[12px] font-medium text-emerald-700"><Check className="h-3.5 w-3.5" />{t('saved_recipe')}</span>
        : onSave && (
          <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-[12.5px] font-medium text-slate-700">
            <input type="checkbox" checked={!!save} onChange={(e) => onSave(e.target.checked)} className="h-4 w-4 accent-[#0b2f6b]" />
            {t('save_recipe')}
          </label>
        ))}
    </div>
  )
}

/** Step 2: the customer checks and edits the ingredient list before any product is picked. */
export function Ingredients({ plan, onApprove }: { plan: Plan; onApprove: (items: PlanItemOut[], save: string[]) => Promise<void> }) {
  const nextId = useRef(plan.items.length)
  const [rows, setRows] = useState<Row[]>(() => plan.items.map((i, n) => ({
    id: n, key: i.key, name: i.name, qty: fmt(i.quantity), unit: UNITS.includes(i.unit) ? i.unit : i.unit === 'unit' ? 'pcs' : i.unit, dish: i.dish ?? null, orig: i,
  })))
  const [save, setSave] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [focus, setFocus] = useState<number | null>(null)

  const patch = (id: number, p: Partial<Row>) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...p } : r)))
  const step = (r: Row, dir: 1 | -1) => {
    const q = toNum(r.qty)
    const s = r.unit === 'pcs' ? 1 : q < 2 || (dir < 0 && q <= 2) ? 0.1 : 0.5
    patch(r.id, { qty: fmt(Math.max(0, q + dir * s)) })
  }
  const add = (dish: string | null) => {
    const id = ++nextId.current
    setRows((rs) => [...rs, { id, key: null, name: '', qty: '1', unit: 'kg', dish, orig: null }])
    setFocus(id)
  }

  const valid = rows.filter((r) => r.name.trim() && toNum(r.qty) > 0)
  const edits = rows.filter(changed).length + plan.items.filter((i) => !rows.some((r) => r.key === i.key)).length

  const approve = async () => {
    setBusy(true)
    await onApprove(
      valid.map((r) => ({ key: r.key, name: r.name.trim(), quantity: toNum(r.qty), unit: r.unit, dish: r.dish })),
      plan.dishes.filter((d) => d.source !== 'recipe' && save[d.name]).map((d) => d.name),
    )
    setBusy(false)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-5">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-[19px] font-semibold text-slate-900">{t('check_ingredients')}</h2>
          <span className="shrink-0 text-[13px] text-slate-500">
            {plan.title}{plan.deliver_by && <> · {t('delivery_lc')} <span className="font-medium text-slate-700">{fDay(plan.deliver_by)}</span></>}
          </span>
        </div>

        <div className="mt-4 space-y-5">
          {groupsOf(plan.dishes, rows).map((g) => (
            <section key={g.id}>
              <DishHead dish={g.dish} save={g.dish ? save[g.dish.name] : false}
                onSave={g.dish ? (v) => setSave((s) => ({ ...s, [g.dish!.name]: v })) : undefined} />
              <div className="mt-2 divide-y divide-slate-100 overflow-hidden rounded-xl bg-white ring-1 ring-slate-200/80">
                {g.items.map((r) => (
                  <div key={r.id} className="flex items-center gap-2 px-3 py-1">
                    <span title={changed(r) ? t('edited') : undefined}
                      className={cx('h-1.5 w-1.5 shrink-0 rounded-full', changed(r) ? 'bg-[#1f4fbf]' : 'bg-transparent')} />
                    <input value={r.name} onChange={(e) => patch(r.id, { name: e.target.value })} placeholder={t('ingredient_ph')}
                      autoFocus={focus === r.id}
                      className="min-w-0 flex-1 rounded-md border-0 bg-transparent px-1.5 py-1.5 text-[14px] text-slate-800 placeholder:text-slate-300 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none focus:ring-1 focus:ring-[#1f4fbf]/40" />
                    <div className="flex shrink-0 items-center rounded-lg ring-1 ring-slate-200">
                      <button type="button" onClick={() => step(r, -1)} title={t('less')}
                        className="grid h-8 w-8 place-items-center rounded-l-lg text-slate-500 hover:bg-slate-100"><Minus className="h-3.5 w-3.5" /></button>
                      <input value={r.qty} inputMode="decimal" onChange={(e) => patch(r.id, { qty: e.target.value.replace(/[^\d.,]/g, '') })}
                        className="h-8 w-14 border-0 bg-transparent text-center text-[14px] font-medium tabular-nums text-slate-900 focus:outline-none" />
                      <button type="button" onClick={() => step(r, 1)} title={t('more')}
                        className="grid h-8 w-8 place-items-center rounded-r-lg text-slate-500 hover:bg-slate-100"><Plus className="h-3.5 w-3.5" /></button>
                    </div>
                    <select value={r.unit} onChange={(e) => patch(r.id, { unit: e.target.value })}
                      className="h-8 w-16 shrink-0 rounded-lg border-0 bg-white px-1.5 text-[13px] text-slate-700 ring-1 ring-slate-200 focus:outline-none">
                      {(UNITS.includes(r.unit) ? UNITS : [...UNITS, r.unit]).map((u) => <option key={u} value={u}>{fUnit(u)}</option>)}
                    </select>
                    <button type="button" title={t('remove')} onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}
                      className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-300 hover:bg-red-50 hover:text-red-500"><X className="h-4 w-4" /></button>
                  </div>
                ))}
                <button type="button" onClick={() => add(g.dish?.name ?? null)}
                  className="flex w-full items-center gap-1.5 px-4 py-2 text-[13px] font-medium text-[#1f4fbf] hover:bg-[#eef3fc]">
                  <Plus className="h-4 w-4" /> {t('add_ingredient')}
                </button>
              </div>
            </section>
          ))}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-4 border-t border-slate-200 bg-white px-8 py-3.5">
        <div className="text-[12.5px] text-slate-500">
          {t('nothing_ordered')}{edits > 0 && <span className="ml-1.5 font-medium text-[#1f4fbf]">{tn('edits_one', 'edits_other', edits)}</span>}
        </div>
        <button type="button" disabled={busy || valid.length === 0} onClick={approve}
          className="ml-auto flex items-center gap-2 rounded-xl bg-[#0b2f6b] px-5 py-2.5 text-[14.5px] font-semibold text-white shadow-sm transition hover:bg-[#123d86] disabled:bg-slate-300">
          {busy && <Spinner className="h-4 w-4" />}
          {t('looks_right')}
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

/** The approved (or being-revised) list, read-only. */
export function PlanList({ plan }: { plan: Plan }) {
  return (
    <div className="space-y-4">
      {groupsOf(plan.dishes, plan.items).map((g) => (
        <section key={g.id}>
          <DishHead dish={g.dish} />
          <div className="mt-1.5 grid grid-cols-2 gap-x-8 rounded-xl bg-white px-4 py-2 ring-1 ring-slate-200/80">
            {g.items.map((i) => (
              <div key={i.key} className="flex items-baseline justify-between gap-3 border-b border-slate-100 py-1.5 text-[13px] last:border-0">
                <span className="truncate text-slate-700">{i.name}</span>
                <span className="shrink-0 font-medium tabular-nums text-slate-900">{fNum(i.quantity)} {fUnit(i.unit)}</span>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
