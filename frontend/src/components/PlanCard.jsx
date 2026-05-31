import { useState } from 'react'

const TIER_STYLES = {
  Silver: {
    badge: 'bg-gray-100 text-gray-700 border border-gray-300',
    border: 'border-t-4 border-t-gray-400',
    dot: 'bg-gray-400',
  },
  Gold: {
    badge: 'bg-amber-100 text-amber-700 border border-amber-300',
    border: 'border-t-4 border-t-amber-400',
    dot: 'bg-amber-400',
  },
  Platinum: {
    badge: 'bg-purple-100 text-purple-700 border border-purple-300',
    border: 'border-t-4 border-t-purple-500',
    dot: 'bg-purple-500',
  },
}

function formatINR(amount) {
  if (!amount && amount !== 0) return '—'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

function BoolIcon({ value }) {
  return value ? <span>✅</span> : <span className="opacity-50">❌</span>
}

export default function PlanCard({ plan, onSelect }) {
  const [expanded, setExpanded] = useState(false)
  const tier = plan.tier ? plan.tier.charAt(0).toUpperCase() + plan.tier.slice(1) : 'Silver'
  const styles = TIER_STYLES[tier] || TIER_STYLES.Silver
  const highlights = plan.highlights || plan.key_highlights || []

  return (
    <div className={`bg-white rounded-xl shadow-md hover:shadow-lg transition-shadow flex flex-col ${styles.border}`}>
      <div className="p-6 flex flex-col flex-1">
        {/* Header */}
        <div className="flex items-start justify-between gap-2 mb-4">
          <h3 className="text-xl font-bold text-gray-900 leading-tight">{plan.plan_name}</h3>
          <span className={`text-xs font-semibold px-2 py-1 rounded-full whitespace-nowrap ${styles.badge}`}>
            {tier}
          </span>
        </div>

        {/* Premium */}
        <div className="mb-4">
          <div className="text-3xl font-extrabold text-teal-600">
            {formatINR(plan.annual_premium)}
          </div>
          <div className="text-sm text-gray-500">/year</div>
        </div>

        {/* Key stats */}
        <div className="grid grid-cols-2 gap-3 mb-4 text-sm">
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="text-gray-500 text-xs mb-1">Sum Insured</div>
            <div className="font-semibold text-gray-800">{formatINR(plan.sum_insured)}</div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="text-gray-500 text-xs mb-1">Co-payment</div>
            <div className="font-semibold text-gray-800">
              {plan.co_payment_pct === 0 ? 'Zero Co-pay' : `${plan.co_payment_pct}%`}
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3 col-span-2">
            <div className="text-gray-500 text-xs mb-1">PED Waiting Period</div>
            <div className="font-semibold text-gray-800">
              {plan.ped_waiting_months ? `${plan.ped_waiting_months} months` : '—'}
            </div>
          </div>
        </div>

        {/* Highlights */}
        {highlights.length > 0 && (
          <div className="mb-4">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              Key Highlights
            </div>
            <ul className="space-y-1">
              {highlights.slice(0, 3).map((h, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                  <span className={`mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${styles.dot}`} />
                  {h}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Toggle button */}
        <button
          onClick={() => setExpanded(e => !e)}
          className="text-sm text-teal-600 hover:text-teal-800 font-medium mb-3 text-left transition-colors hover:underline underline-offset-2"
        >
          {expanded ? 'Hide Details ▲' : 'View Plan Details ▼'}
        </button>

        {/* Expandable details */}
        <div
          className={`overflow-hidden transition-all duration-300 ease-in-out ${
            expanded ? 'max-h-[1200px] opacity-100' : 'max-h-0 opacity-0'
          }`}
        >
          <div className="border-t border-gray-100 pt-4 mb-4 space-y-5">
            {/* Coverage Details */}
            <div>
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Coverage Details
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <div className="text-gray-500">Room Rent Limit</div>
                <div className="font-medium text-gray-800">{plan.room_rent_limit || '—'}</div>

                <div className="text-gray-500">Initial Waiting Period</div>
                <div className="font-medium text-gray-800">
                  {plan.initial_waiting_days != null ? `${plan.initial_waiting_days} days` : '—'}
                </div>

                <div className="text-gray-500">Network Hospitals</div>
                <div className="font-medium text-gray-800">
                  {plan.network_hospitals ? plan.network_hospitals.toLocaleString() : '—'}
                </div>

                <div className="text-gray-500">Policy Tenure</div>
                <div className="font-medium text-gray-800">{plan.policy_tenure_options || '—'}</div>

                <div className="text-gray-500">Renewability</div>
                <div className="font-medium text-gray-800">{plan.renewability || '—'}</div>
              </div>
            </div>

            {/* Benefits */}
            <div>
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Benefits
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <div className="text-gray-500">Restoration Benefit</div>
                <div><BoolIcon value={plan.restoration_benefit} /></div>

                <div className="text-gray-500">Daycare Procedures</div>
                <div><BoolIcon value={plan.daycare_covered} /></div>

                <div className="text-gray-500">Maternity Cover</div>
                <div><BoolIcon value={plan.maternity_covered} /></div>

                <div className="text-gray-500">Critical Illness Cover</div>
                <div><BoolIcon value={plan.critical_illness_cover} /></div>

                <div className="text-gray-500">Teleconsultation</div>
                <div><BoolIcon value={plan.teleconsult} /></div>

                <div className="text-gray-500">AYUSH Treatment</div>
                <div><BoolIcon value={plan.ayush_covered} /></div>

                <div className="text-gray-500">Annual Health Checkup</div>
                <div><BoolIcon value={plan.annual_checkup} /></div>

                <div className="text-gray-500">Ambulance Cover</div>
                <div className="font-medium text-gray-800">
                  {plan.ambulance_cover ? `₹${plan.ambulance_cover.toLocaleString()}` : '—'}
                </div>
              </div>
            </div>

            {/* NCB */}
            <div>
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                No Claim Bonus
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <div className="text-gray-500">No Claim Bonus</div>
                <div className="font-medium text-gray-800">
                  {plan.no_claim_bonus_pct != null ? `${plan.no_claim_bonus_pct}% per year` : '—'}
                </div>

                <div className="text-gray-500">Maximum NCB</div>
                <div className="font-medium text-gray-800">
                  {plan.max_ncb_pct != null ? `${plan.max_ncb_pct}%` : '—'}
                </div>
              </div>
            </div>

            {/* Key Exclusions */}
            {plan.key_exclusions && (
              <div>
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Key Exclusions
                </div>
                <div className="flex flex-wrap gap-1">
                  {plan.key_exclusions.split(',').map((ex, i) => (
                    <span
                      key={i}
                      className="text-xs bg-red-50 text-red-700 border border-red-200 px-2 py-0.5 rounded-full"
                    >
                      {ex.trim()}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* AI Recommendation */}
        {plan.reason && (
          <div className="mb-4 bg-teal-50 rounded-lg p-3">
            <div className="text-xs font-semibold text-teal-700 mb-1">AI Recommendation</div>
            <p className="text-sm text-teal-800 italic leading-relaxed">{plan.reason}</p>
          </div>
        )}

        {/* Select button */}
        <div className="mt-auto pt-2">
          <button
            onClick={() => onSelect(plan)}
            className="w-full bg-teal-600 hover:bg-teal-700 text-white font-semibold py-3 px-4 rounded-lg transition-colors"
          >
            Select This Plan
          </button>
        </div>
      </div>
    </div>
  )
}
