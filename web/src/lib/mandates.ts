import type { MandateSummary } from '../types'

// Short, human-readable summary of each buyer's signed purchasing mandate (vc+jwt).
// The console API does not expose mandates, so these mirror data/state/mandates/*.jwt.
export const MANDATES: Record<string, MandateSummary> = {
  'hotel-aurora': {
    agentId: 'aurora-procure-bot',
    approver: 'Laura Mäkinen (F&B Manager)',
    facts: [
      { label: 'Auto-approve', value: 'orders ≤ €1,500' },
      { label: 'Weekly budget', value: '€12,000' },
      { label: 'Hard limit', value: '€20,000 per order' },
      { label: 'Unconfirmed stock', value: 'needs approval' },
    ],
  },
  'espoo-childrens-hospital': {
    agentId: 'hospital-kitchen-agent',
    approver: 'Anna Virtanen (Clinical Dietitian)',
    facts: [
      { label: 'Auto-approve', value: 'orders ≤ €800' },
      { label: 'Must avoid', value: 'peanuts, tree nuts, sesame' },
      { label: 'Unverified allergen data', value: 'needs approval' },
      { label: 'Weekly budget', value: '€6,000' },
    ],
  },
}

export function approverFor(buyerId: string | undefined | null): string {
  return (buyerId && MANDATES[buyerId]?.approver) || ''
}

export function shortBuyer(id: string | null | undefined, buyers: { id: string; name: string }[]): string {
  if (!id) return 'Valio'
  const b = buyers.find((x) => x.id === id)
  if (!b) return id
  return b.name.replace(/ Group$/, '').replace(/ Kitchen$/, '')
}
