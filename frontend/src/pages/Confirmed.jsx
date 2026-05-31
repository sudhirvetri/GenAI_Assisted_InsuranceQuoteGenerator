import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import LoadingSpinner from '../components/LoadingSpinner'

const API_BASE = 'https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1'

function formatINR(amount) {
  if (!amount && amount !== 0) return '—'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

export default function Confirmed() {
  const location = useLocation()
  const navigate = useNavigate()
  const { token } = useAuth()
  const { plan, transactionId } = location.state || {}

  const [submitting, setSubmitting] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!plan || !transactionId || !token) return

    setSubmitting(true)
    fetch(`${API_BASE}/selections`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        transaction_id: transactionId,
        plan_id: plan.plan_id,
      }),
    })
      .then(async res => {
        if (res.status === 409) {
          // Already selected — treat as success
          const data = await res.json().catch(() => ({}))
          setSelectedPlan(plan)
          setError(null)
          setSubmitting(false)
          return
        }
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new Error(data.message || `Failed (${res.status})`)
        }
        return res.json()
      })
      .then(() => setConfirmed(true))
      .catch(err => setError(err.message || 'Selection could not be saved.'))
      .finally(() => setSubmitting(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!plan) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="text-gray-600 mb-4">No plan selected.</p>
          <button
            onClick={() => navigate('/')}
            className="text-teal-600 font-semibold hover:underline"
          >
            Start Over
          </button>
        </div>
      </div>
    )
  }

  const TIER_COLORS = {
    Silver: 'bg-gray-100 text-gray-700',
    Gold: 'bg-amber-100 text-amber-700',
    Platinum: 'bg-purple-100 text-purple-700',
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <Navbar />

      <main className="flex-1 flex items-center justify-center py-12 px-4">
        <div className="max-w-lg w-full">
          {submitting && (
            <div className="bg-white rounded-xl shadow-md p-10 text-center">
              <LoadingSpinner message="Saving your selection..." />
            </div>
          )}

          {!submitting && error && (
            <div className="bg-white rounded-xl shadow-md p-8 text-center">
              <div className="text-4xl mb-4">⚠️</div>
              <h2 className="text-xl font-bold text-gray-900 mb-2">Selection Error</h2>
              <p className="text-gray-500 text-sm mb-6">{error}</p>
              <button
                onClick={() => navigate(-1)}
                className="bg-teal-600 hover:bg-teal-700 text-white font-semibold px-6 py-3 rounded-lg transition-colors"
              >
                Go Back
              </button>
            </div>
          )}

          {!submitting && confirmed && (
            <div className="bg-white rounded-xl shadow-md overflow-hidden">
              <div className="bg-teal-600 py-8 px-6 text-center text-white">
                <div className="text-5xl mb-3">🎉</div>
                <h1 className="text-2xl font-extrabold">You've Selected</h1>
                <h2 className="text-xl font-bold mt-1 text-teal-100">{plan.plan_name}</h2>
              </div>

              <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <span
                    className={`text-sm font-semibold px-3 py-1 rounded-full ${
                      TIER_COLORS[plan.tier] || 'bg-gray-100 text-gray-700'
                    }`}
                  >
                    {plan.tier} Tier
                  </span>
                  <div className="text-right">
                    <div className="text-2xl font-extrabold text-teal-600">
                      {formatINR(plan.annual_premium)}
                    </div>
                    <div className="text-xs text-gray-500">/year</div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 mb-6 text-sm">
                  <div className="bg-gray-50 rounded-lg p-3">
                    <div className="text-gray-500 text-xs mb-0.5">Sum Insured</div>
                    <div className="font-semibold">{formatINR(plan.sum_insured)}</div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3">
                    <div className="text-gray-500 text-xs mb-0.5">Co-payment</div>
                    <div className="font-semibold">
                      {plan.co_payment_pct === 0 ? 'Zero Co-pay' : `${plan.co_payment_pct}%`}
                    </div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3 col-span-2">
                    <div className="text-gray-500 text-xs mb-0.5">PED Waiting Period</div>
                    <div className="font-semibold">
                      {plan.ped_waiting_months ? `${plan.ped_waiting_months} months` : '—'}
                    </div>
                  </div>
                </div>

                {plan.key_highlights && plan.key_highlights.length > 0 && (
                  <div className="mb-6">
                    <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                      Plan Benefits
                    </div>
                    <ul className="space-y-1.5">
                      {plan.key_highlights.map((h, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                          <span className="text-teal-500 mt-0.5">✓</span>
                          {h}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6 text-sm text-green-800">
                  A SwiftCare representative will contact you within 24 hours to complete your enrollment.
                </div>

                <button
                  onClick={() => navigate('/')}
                  className="w-full border-2 border-teal-600 text-teal-600 hover:bg-teal-50 font-semibold py-3 rounded-xl transition-colors"
                >
                  Start Over
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
