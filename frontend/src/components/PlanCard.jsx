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

export default function PlanCard({ plan, onSelect }) {
  const tier = plan.tier ? plan.tier.charAt(0).toUpperCase() + plan.tier.slice(1) : 'Silver'
  const styles = TIER_STYLES[tier] || TIER_STYLES.Silver

  return (
    <div className={`bg-white rounded-xl shadow-md hover:shadow-lg transition-shadow flex flex-col ${styles.border}`}>
      <div className="p-6 flex flex-col flex-1">
        <div className="flex items-start justify-between gap-2 mb-4">
          <h3 className="text-xl font-bold text-gray-900 leading-tight">{plan.plan_name}</h3>
          <span className={`text-xs font-semibold px-2 py-1 rounded-full whitespace-nowrap ${styles.badge}`}>
            {tier}
          </span>
        </div>

        <div className="mb-4">
          <div className="text-3xl font-extrabold text-teal-600">
            {formatINR(plan.annual_premium)}
          </div>
          <div className="text-sm text-gray-500">/year</div>
        </div>

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

        {plan.key_highlights && plan.key_highlights.length > 0 && (
          <div className="mb-4">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              Key Highlights
            </div>
            <ul className="space-y-1">
              {plan.key_highlights.slice(0, 3).map((h, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                  <span className={`mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${styles.dot}`} />
                  {h}
                </li>
              ))}
            </ul>
          </div>
        )}

        {plan.reason && (
          <div className="mb-4 bg-teal-50 rounded-lg p-3">
            <div className="text-xs font-semibold text-teal-700 mb-1">AI Recommendation</div>
            <p className="text-sm text-teal-800 italic leading-relaxed">{plan.reason}</p>
          </div>
        )}

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
