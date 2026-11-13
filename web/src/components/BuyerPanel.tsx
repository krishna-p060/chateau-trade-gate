import { Building2, HeartPulse, MapPin, Play, Send, UserCheck } from 'lucide-react'
import { useState } from 'react'
import { MANDATES } from '../lib/mandates'
import type { Buyer, Scenario } from '../types'
import { Spinner } from './ToolSteps'
import { Card, SectionTitle, cx } from './ui'

interface Props {
  buyers: Buyer[]
  scenarios: Scenario[]
  selected: string
  onSelect: (id: string) => void
  onRun: (buyerId: string, request: string) => void
  busy: boolean // a run is being started or is running
}

export function BuyerPanel({ buyers, scenarios, selected, onSelect, onRun, busy }: Props) {
  const [text, setText] = useState('')
  const buyer = buyers.find((b) => b.id === selected)
  const mandate = MANDATES[selected]
  const mine = scenarios.filter((s) => s.buyer_id === selected)

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto pb-2 pr-1">
      <div>
        <SectionTitle>Buyer</SectionTitle>
        <div className="grid grid-cols-2 gap-1 rounded-xl bg-slate-200/70 p-1">
          {buyers.map((b) => {
            const Icon = b.id.includes('hospital') ? HeartPulse : Building2
            return (
              <button type="button" key={b.id} onClick={() => onSelect(b.id)}
                className={cx('flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-[12.5px] font-semibold transition',
                  b.id === selected ? 'bg-white text-valio-700 shadow-sm' : 'text-slate-600 hover:text-slate-900')}>
                <Icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{b.name.replace(/ Group$/, '').replace(/ Kitchen$/, '').replace("Espoo Children's Hospital", 'Children’s Hospital')}</span>
              </button>
            )
          })}
        </div>
      </div>

      {buyer && (
        <Card className="p-4">
          <div className="text-[15px] font-bold text-slate-900">{buyer.name}</div>
          {buyer.profile?.segment && <div className="mt-0.5 text-[12.5px] text-slate-500">{buyer.profile.segment}</div>}
          {buyer.profile?.delivery_address && (
            <div className="mt-1.5 flex items-center gap-1.5 text-[12px] text-slate-500"><MapPin className="h-3.5 w-3.5" />{buyer.profile.delivery_address}</div>
          )}
          {mandate && (
            <>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Signed mandate</span>
                <span className="font-mono text-[10.5px] text-slate-400">{mandate.agentId}</span>
              </div>
              <dl className="mt-1.5 space-y-1">
                {mandate.facts.map((f) => (
                  <div key={f.label} className="flex justify-between gap-3 text-[12.5px]">
                    <dt className="text-slate-500">{f.label}</dt>
                    <dd className="text-right font-semibold text-slate-800">{f.value}</dd>
                  </div>
                ))}
              </dl>
              <div className="mt-3 flex items-center gap-2 rounded-lg bg-amber-50 px-2.5 py-2 text-[12px] text-amber-900 ring-1 ring-amber-100">
                <UserCheck className="h-4 w-4 shrink-0 text-amber-600" />
                <span>Approver: <span className="font-semibold">{mandate.approver}</span></span>
              </div>
            </>
          )}
        </Card>
      )}

      <div>
        <SectionTitle>Scenarios</SectionTitle>
        <div className="space-y-2">
          {mine.map((s) => (
            <Card key={s.id} className="group p-3 transition hover:ring-valio-300">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-semibold leading-snug text-slate-900">{s.title}</div>
                  {s.brief && <div className="mt-0.5 text-[12px] leading-snug text-slate-500">{s.brief}</div>}
                </div>
                <button type="button" disabled={busy} onClick={() => onRun(s.buyer_id, s.request)} title={s.request}
                  className="flex shrink-0 items-center gap-1 rounded-lg bg-valio-600 px-2.5 py-1.5 text-[12px] font-semibold text-white shadow-sm transition hover:bg-valio-700 disabled:cursor-not-allowed disabled:bg-slate-300">
                  {busy ? <Spinner className="h-3 w-3" /> : <Play className="h-3.5 w-3.5 fill-current" />} Run
                </button>
              </div>
              <div className="mt-2 line-clamp-2 text-[12px] italic leading-snug text-slate-500">“{s.request}”</div>
            </Card>
          ))}
          {mine.length === 0 && <div className="px-1 text-[12.5px] text-slate-400">No scenarios for this buyer.</div>}
        </div>
      </div>

      <div>
        <SectionTitle>Your own request</SectionTitle>
        <Card className="p-2">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && text.trim() && !busy) onRun(selected, text.trim())
            }}
            placeholder={selected.includes('hospital') ? 'e.g. 20 kg of gluten-free pasta for Wednesday…' : 'e.g. 200 kg of potatoes for Tuesday…'}
            className="w-full resize-none rounded-lg border-0 bg-transparent p-1.5 text-[13px] text-slate-800 placeholder:text-slate-400 focus:outline-none" />
          <div className="flex items-center justify-between px-1.5 pb-0.5">
            <span className="text-[11px] text-slate-400">as {buyer?.name.split(' ').slice(0, 2).join(' ') || 'buyer'} · ⌘↵</span>
            <button type="button" disabled={busy || !text.trim()} onClick={() => onRun(selected, text.trim())}
              className="flex items-center gap-1.5 rounded-lg bg-valio-600 px-3 py-1.5 text-[12px] font-semibold text-white shadow-sm hover:bg-valio-700 disabled:cursor-not-allowed disabled:bg-slate-300">
              <Send className="h-3.5 w-3.5" /> Run agent
            </button>
          </div>
        </Card>
      </div>
    </div>
  )
}
