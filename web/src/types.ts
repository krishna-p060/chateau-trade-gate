// Shapes returned by the Trade Gate console API. Everything is optional-tolerant: the UI must
// never crash on a missing field, so consumers read these defensively.

export type OrderStatus = 'CONFIRMED' | 'PENDING_APPROVAL' | 'REJECTED' | string
export type Outcome = 'AUTO' | 'APPROVAL' | 'BLOCKED' | string

export interface Buyer {
  id: string
  name: string
  profile?: {
    segment?: string
    delivery_address?: string
    customer_number?: string
    preferences?: { labels?: string[]; brands?: string[] }
  }
}

export interface Scenario {
  id: string
  title: string
  buyer_id: string
  request: string
  brief?: string
  expect?: Record<string, unknown>
}

export interface Issue {
  code?: string
  severity?: string
  message?: string
}

export interface QuoteLine {
  product_id: string
  name?: string
  units?: number
  sales_unit?: string
  unit_price?: number
  line_total?: number
  stock_status?: string
  earliest_delivery?: string
  earliest_delivery_confirmed?: boolean
  meets_deadline?: boolean
  delivery_reliability?: number | null
  sustainability_labels?: string[]
  co2_kg?: number | null
  issues?: Issue[]
  content_per_sales_unit?: number
  content_dim?: string
}

export interface Quote {
  quote_id: string
  lines?: QuoteLine[]
  total_price?: number
  total_price_with_tax?: number
  deliver_by?: string
  expires_at?: string
  issued_at?: string
}

export interface Finding {
  rule?: string
  outcome?: Outcome
  message?: string
  product_id?: string | null
}

export interface Approval {
  id: string
  order_id: string
  buyer_id: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | string
  created?: string
  decided?: string | null
  approver?: string | null
  note?: string | null
  reasons?: string[]
  order?: Order
}

export interface Order {
  id: string
  buyer_id: string
  quote_id?: string
  status: OrderStatus
  created?: string
  updated?: string
  total?: number
  agent_id?: string
  rationale?: string
  decision?: { outcome?: Outcome; findings?: Finding[] } | null
  quote?: Quote | null
  approval?: Partial<Approval> | null
  confirmation_jws?: string | null
}

export interface AuditEntry {
  seq: number
  ts: string
  buyer_id: string | null
  actor: string
  event: string
  summary: string
  ref: string | null
  data: unknown
  prev_hash: string
  hash: string
}

export interface Integrity {
  valid: boolean
  checked?: number
  head?: string
  broken_at_seq?: number
}

export interface Stats {
  orders?: Record<string, { count: number; total: number }>
  valio_api_calls?: number
  audit?: Integrity
}

export interface AgentEvent {
  kind: string
  run_id: string
  buyer_id?: string
  ts?: string
  // payload, depending on kind
  request?: string
  model?: string
  text?: string
  tool?: string
  input?: Record<string, unknown>
  ok?: boolean
  preview?: string
  orders?: string[]
}

export interface AgentRun {
  id: string
  buyer_id: string
  request: string
  status: 'running' | 'done' | 'error' | string
  events: AgentEvent[]
  final?: string
}

export interface Manifest {
  name?: string
  description?: string
  version?: string
  protocols?: Record<string, string>
  signing?: { alg?: string; jwks_uri?: string }
  mandate_format?: string
  flow?: string[]
  guardrail_outcomes?: string[]
  assumptions?: string[]
}

// Hard-coded mandate summaries (the console API does not expose mandates; these mirror the
// signed mandate credentials in data/state/mandates/*.jwt).
export interface MandateSummary {
  approver: string
  facts: { label: string; value: string }[]
  agentId: string
}
