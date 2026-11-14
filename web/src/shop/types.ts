// Shapes returned by the webshop (Aimo Assistant) API. Read defensively: older snapshots may lack fields.

export interface Contact {
  name: string
  role?: string
}

export interface StandingOrder {
  id: string
  name: string
  weekdays: string[]
  lines: { product_id: string; units: number; name: string }[]
}

export interface Customer {
  id: string
  name: string
  segment?: string
  contact?: Contact
  delivery_address?: string
  delivery_days?: string[]
  priorities?: string[]
  rules?: {
    avoid_allergens?: string[]
    require_allergen_data?: boolean
    orders_up_to_eur_confirmed_by_contact?: number
    above_that_approved_by?: string[]
  }
  settings?: { auto_confirm_standing_orders?: boolean }
  approval_limit_eur?: number | null
  approvers?: string[]
  standing_orders?: StandingOrder[]
  recipes?: Recipe[]
  usual_products?: { product_id: string; name: string; name_fi?: string }[]
  suggestions?: string[]
}

export interface Recipe {
  id: string
  name: string
  portions?: number
  ingredients?: { name: string; quantity?: number; unit?: string; product_id?: string; product_name?: string }[]
}

export interface Question {
  id: string
  text: string
  options: string[]
}

export interface Funnel {
  catalog_size?: number
  matched?: number
  checked_live?: number
  shortlisted?: number
}

export interface PlanDish {
  name: string
  portions?: number | null
  source?: 'recipe' | 'estimate' | string
  recipe_name?: string | null
  recipe_portions?: number | null
  saved?: boolean
}

export interface PlanItem {
  key: string
  name: string
  quantity: number
  unit: string
  dish?: string | null
  source?: 'recipe' | 'estimate' | 'added' | string
  edited?: boolean
}

export interface Plan {
  title?: string
  deliver_by?: string
  status: 'proposed' | 'revising' | 'approved' | string
  changes?: string[]
  dishes: PlanDish[]
  items: PlanItem[]
}

/** What the customer sends back when approving the ingredient list. */
export interface PlanItemOut {
  key: string | null
  name: string
  quantity: number
  unit: string
  dish: string | null
}

export interface Check {
  id: 'spend' | 'allergens' | 'delivery' | string
  level: 'ok' | 'warn' | 'block' | string
  label: string
}

export type Role = 'user' | 'assistant' | 'progress' | 'question' | 'notice' | 'error'

export interface Message {
  id: string
  role: Role
  text: string
  ts?: string
  options?: string[]
  questions?: Question[]
  funnel?: Funnel
  order_id?: string
  status?: string
}

export interface Delivery {
  date?: string | null
  earliest?: string | null
  on_time?: boolean
  confirmed?: boolean
}

export interface Option {
  product_id: string
  name: string
  name_fi?: string | null
  brand?: string | null
  pack?: string
  units: number
  sales_unit?: string
  unit_price?: number
  total: number
  total_with_tax?: number | null
  /** Valio's order cut-off ("closing time") for this product and delivery date. */
  order_by?: string | null
  price_per?: string | null
  delivered_qty?: number
  delivery?: Delivery
  stock?: string
  stock_tracked?: boolean
  co2_kg?: number | null
  labels?: string[]
  diet?: string[]
  allergens?: string[]
  may_contain?: string[]
  allergen_data?: boolean
  country?: string | null
  usual?: boolean
  times_bought?: number
  valio_substitute?: boolean
  notes?: string[]
  note_codes?: string[]
  why?: string
}

export interface Line {
  key: string
  need: string
  dish?: string | null
  quantity?: number
  unit?: string
  decision_needed?: boolean
  replaces?: { product_id: string; name: string; name_fi?: string | null } | null
  selected: number
  problem?: string | null
  notify?: boolean
  options: Option[]
}

export interface Cart {
  title?: string
  deliver_by?: string
  assumptions?: string[]
  updated?: string
  portions?: number | null
  reference?: string
  saved_template?: string | null
  checks?: Check[]
  lines: Line[]
  totals?: {
    total?: number
    total_with_tax?: number | null
    per_portion?: number | null
    order_by?: string | null
    co2_kg?: number
    lines?: number
    late?: number
    choices_open?: number
    delivery?: string
  }
}

export interface OrderInfo {
  order_id: string
  status: 'CONFIRMED' | 'PENDING_APPROVAL' | 'REJECTED' | string
  total?: number
  total_with_tax?: number
  delivery?: string
  reasons?: string[]
  accepted?: string[]
  approver?: string | null
  confirmed_by?: string | null
  signed?: boolean
  note?: string | null
  reference?: string | null
}

export interface Session {
  id: string
  customer_id: string
  lang?: string
  status: 'idle' | 'working' | 'waiting' | 'review' | 'cart' | 'ordering' | 'ordered' | 'error' | string
  step?: 'request' | 'ingredients' | 'products' | 'order' | string
  busy: boolean
  messages: Message[]
  question: { questions?: Question[] } | null
  plan?: Plan | null
  cart: Cart | null
  order: OrderInfo | null
}
