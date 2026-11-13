import { ArrowRight, BookOpen, Braces, CheckCircle2, Clock, ExternalLink, FileSignature, KeyRound, Plug, ShieldCheck, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Manifest } from '../types'
import { Card, cx } from './ui'

const MCP_TOOLS: [string, string][] = [
  ['get_my_mandate', 'What the buyer authorises: spend limits, allergen rules, approvers. Called first.'],
  ['search_products', 'Search the Valio Aimo catalog (English or Finnish) with diet, allergen, label and unit filters.'],
  ['get_product', 'Full static product details: ingredients, allergens, labels, pack size, substitutes.'],
  ['check_offers', 'Live Valio price and availability, converted into packs, cut-offs and delivery dates.'],
  ['plan_purchase', 'Turn a need into good / better / best options, split orders and ruled-out products with reasons.'],
  ['create_quote', 'Lock fixed prices for an exact basket: a quote signed by Valio (EdDSA), valid 2 hours.'],
  ['place_order', 'Commit a quote; the gate applies the mandate: confirmed, pending approval or blocked.'],
  ['get_order', 'Order status, approval state and the signed confirmation.'],
  ['get_audit_trail', 'Plain-language log of what the agent and the gate did, plus chain integrity.'],
]

const OUTCOMES: Record<string, { icon: typeof CheckCircle2; tone: string; text: string }> = {
  AUTO: { icon: CheckCircle2, tone: 'bg-emerald-50 text-emerald-800 ring-emerald-200', text: 'Inside the mandate: confirmed at once with a signed confirmation.' },
  APPROVAL: { icon: Clock, tone: 'bg-amber-50 text-amber-900 ring-amber-200', text: 'Outside the agent’s authority: a named human decides, with the reasons in plain language.' },
  BLOCKED: { icon: XCircle, tone: 'bg-red-50 text-red-800 ring-red-200', text: 'Never allowed (e.g. allergen conflict): refused, whatever the agent says.' },
}

export function InterfaceTab() {
  const [m, setM] = useState<Manifest | null>(null)
  const [keys, setKeys] = useState<Record<string, string>[]>([])
  const [err, setErr] = useState('')
  useEffect(() => {
    api.manifest().then(setM).catch((e) => setErr(e.message))
    api.jwks().then((j) => setKeys(Array.isArray(j?.keys) ? j.keys : [])).catch(() => {})
  }, [])

  const flow = m?.flow?.length ? m.flow : ['search_products', 'plan_purchase / get_offers', 'create_quote', 'place_order', '(human approval if required)', 'get_order']

  return (
    <div className="mx-auto h-full max-w-[1280px] overflow-y-auto pb-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Open standards, no lock-in</h1>
          <p className="mt-0.5 max-w-3xl text-[13px] text-slate-500">{m?.description || 'Any purchasing agent can discover the gate, prove who it acts for, and verify every quote and order offline.'}</p>
          {err && <p className="mt-1 text-[12.5px] text-red-600">Could not load the manifest: {err}</p>}
        </div>
        <div className="flex gap-2">
          <a href="/docs" target="_blank" rel="noreferrer" className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-[13px] font-semibold text-valio-700 shadow-sm ring-1 ring-slate-200 hover:bg-valio-50">
            <BookOpen className="h-4 w-4" /> API docs (Swagger) <ExternalLink className="h-3.5 w-3.5 opacity-60" />
          </a>
          <a href="/openapi.json" target="_blank" rel="noreferrer" className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-[13px] font-semibold text-valio-700 shadow-sm ring-1 ring-slate-200 hover:bg-valio-50">
            <Braces className="h-4 w-4" /> openapi.json <ExternalLink className="h-3.5 w-3.5 opacity-60" />
          </a>
        </div>
      </div>

      {/* flow */}
      <Card className="mt-4 p-5">
        <div className="mb-3 text-[11px] font-bold uppercase tracking-wider text-slate-400">Agent flow</div>
        <div className="flex flex-wrap items-center gap-2">
          {flow.map((f, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className={cx('rounded-lg px-3 py-2 font-mono text-[12.5px] ring-1',
                f.startsWith('(') ? 'bg-amber-50 text-amber-800 ring-amber-200' : 'bg-valio-50 text-valio-700 ring-valio-200')}>
                <span className="mr-1.5 font-sans text-[11px] font-bold opacity-50">{i + 1}</span>{f.replace(/[()]/g, '')}
              </span>
              {i < flow.length - 1 && <ArrowRight className="h-4 w-4 text-slate-300" />}
            </div>
          ))}
        </div>
      </Card>

      <div className="mt-4 grid grid-cols-3 gap-4">
        <Card className="p-5">
          <Heading icon={<Plug className="h-4 w-4" />}>Protocols</Heading>
          <dl className="space-y-2.5 text-[13px]">
            <Row k="MCP (Streamable HTTP)" v={m?.protocols?.mcp || '/mcp'} wrap />
            <Row k="REST · OpenAPI 3.1" v={m?.protocols?.openapi || '/openapi.json'} wrap />
            <Row k="Discovery" v="/.well-known/trade-gate.json" />
            <Row k="Version" v={m?.version || '—'} />
          </dl>
        </Card>
        <Card className="p-5">
          <Heading icon={<FileSignature className="h-4 w-4" />}>Mandate (who the agent acts for)</Heading>
          <p className="text-[13px] leading-relaxed text-slate-700">{m?.mandate_format || 'W3C Verifiable Credential (vc+jwt), type PurchasingMandate'}</p>
          <p className="mt-2 text-[12.5px] leading-relaxed text-slate-500">Signed by the buyer, sent as <code className="rounded bg-slate-100 px-1 font-mono text-[11.5px]">Authorization: Bearer</code>. Carries spend limits, allergen and diet rules, substitution rules and named approvers. The gate enforces it server-side.</p>
        </Card>
        <Card className="p-5">
          <Heading icon={<KeyRound className="h-4 w-4" />}>Gate signing key (JWKS)</Heading>
          {keys.length === 0 && <p className="text-[13px] text-slate-500">Loading…</p>}
          {keys.map((k, i) => (
            <dl key={i} className="space-y-1.5 text-[12.5px]">
              <Row k="alg" v={`${k.alg || m?.signing?.alg || 'EdDSA'} · ${k.crv || ''}`} />
              <Row k="kid" v={k.kid} />
              <Row k="x" v={k.x} mono wrap />
            </dl>
          ))}
          <p className="mt-2 text-[12px] text-slate-500">Quotes and order confirmations are JWS signed with this key: verify them offline.</p>
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-5 gap-4">
        <Card className="col-span-3 p-5">
          <Heading icon={<Plug className="h-4 w-4" />}>MCP tools for purchasing agents</Heading>
          <ul className="divide-y divide-slate-100">
            {MCP_TOOLS.map(([name, desc]) => (
              <li key={name} className="flex gap-4 py-2">
                <code className="w-36 shrink-0 font-mono text-[12.5px] font-semibold text-valio-700">{name}</code>
                <span className="text-[13px] text-slate-600">{desc}</span>
              </li>
            ))}
          </ul>
        </Card>
        <div className="col-span-2 flex flex-col gap-4">
          <Card className="p-5">
            <Heading icon={<ShieldCheck className="h-4 w-4" />}>Guardrail outcomes</Heading>
            <div className="space-y-2">
              {(m?.guardrail_outcomes?.length ? m.guardrail_outcomes : Object.keys(OUTCOMES)).map((o) => {
                const x = OUTCOMES[o] || { icon: CheckCircle2, tone: 'bg-slate-50 text-slate-700 ring-slate-200', text: '' }
                const Icon = x.icon
                return (
                  <div key={o} className={cx('flex gap-2.5 rounded-lg px-3 py-2 ring-1', x.tone)}>
                    <Icon className="mt-0.5 h-4 w-4 shrink-0" />
                    <div className="text-[12.5px] leading-snug"><span className="font-bold">{o}</span> · {x.text}</div>
                  </div>
                )
              })}
            </div>
          </Card>
          <Card className="p-5">
            <Heading icon={<BookOpen className="h-4 w-4" />}>Stated assumptions</Heading>
            <ul className="list-disc space-y-1.5 pl-5 text-[12.5px] leading-snug text-slate-600 marker:text-slate-300">
              {(m?.assumptions || []).map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  )
}

function Heading({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return <div className="mb-3 flex items-center gap-2 text-[13px] font-bold text-slate-900"><span className="text-valio-600">{icon}</span>{children}</div>
}

function Row({ k, v, mono = true, wrap = false }: { k: string; v?: string; mono?: boolean; wrap?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="shrink-0 text-slate-500">{k}</dt>
      <dd className={cx('min-w-0 text-right text-slate-800', mono && 'font-mono text-[12px]', wrap ? 'break-all' : 'truncate')} title={v}>{v || '—'}</dd>
    </div>
  )
}
