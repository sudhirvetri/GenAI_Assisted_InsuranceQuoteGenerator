import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function categoryLabel(category) {
  if (!category) return '—'
  return category.charAt(0).toUpperCase() + category.slice(1)
}

function StatusBadge({ status }) {
  const styles = {
    COMPLETE: 'bg-green-100 text-green-800',
    PENDING: 'bg-yellow-100 text-yellow-800',
    FAILED: 'bg-red-100 text-red-800',
  }
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${styles[status] || 'bg-gray-100 text-gray-700'}`}>
      {status}
    </span>
  )
}

function QuoteCard({ txn }) {
  const navigate = useNavigate()
  const { profile, recommendations = [] } = txn
  const previewPlans = recommendations.slice(0, 3)

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex flex-col gap-3">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm text-gray-500 mb-1">Generated on {formatDate(txn.created_at)}</p>
          <p className="text-gray-800 font-medium">
            {categoryLabel(profile.category)} &bull; Age {profile.age} &bull; Budget {formatINR(profile.budget_premium)}/yr
          </p>
          <p className="text-sm text-gray-500 mt-0.5">
            Target cover: {formatINR(profile.target_si)}
          </p>
        </div>
        <StatusBadge status={txn.status} />
      </div>

      {/* Selected plan highlight */}
      {txn.selected_plan_id ? (
        <div className="bg-teal-50 border border-teal-200 rounded-lg px-3 py-2">
          <p className="text-xs text-teal-600 font-semibold uppercase tracking-wide mb-0.5">Selected Plan</p>
          <p className="text-teal-800 font-semibold">{txn.selected_plan_id}</p>
          {txn.selected_at && (
            <p className="text-xs text-teal-600 mt-0.5">on {formatDate(txn.selected_at)}</p>
          )}
        </div>
      ) : txn.status === 'COMPLETE' ? (
        <p className="text-sm text-gray-400 italic">No plan selected yet</p>
      ) : null}

      {/* Recommendations preview pills */}
      {previewPlans.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {previewPlans.map(r => (
            <span
              key={r.plan_id}
              className="bg-gray-100 text-gray-600 text-xs px-2.5 py-1 rounded-full"
            >
              {r.plan_name || r.plan_id}
            </span>
          ))}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 mt-1">
        <button
          onClick={() => navigate(`/results/${txn.transaction_id}`)}
          className="flex-1 bg-teal-600 hover:bg-teal-700 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
        >
          View &amp; Select Plans
        </button>
        {txn.selected_plan_id && (
          <button
            onClick={() => navigate(`/results/${txn.transaction_id}`)}
            className="flex-1 border border-teal-600 text-teal-600 hover:bg-teal-50 text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            Change Selection
          </button>
        )}
      </div>
    </div>
  )
}

export default function MyQuotes() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!token) return

    fetch(`${API_BASE}/my-quotes`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(data => {
        if (!data.count || data.count === 0) {
          navigate('/quote-form', { replace: true })
        } else {
          setTransactions(data.transactions.filter(t => t.status === 'COMPLETE') || [])
          setLoading(false)
        }
      })
      .catch(() => {
        navigate('/quote-form', { replace: true })
      })
  }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <LoadingSpinner message="Loading your quotes..." />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* Page header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Your Insurance Quotes</h1>
          <button
            onClick={() => navigate('/quote-form')}
            className="bg-teal-600 hover:bg-teal-700 text-white font-semibold px-5 py-2 rounded-lg transition-colors text-sm"
          >
            Get New Quote
          </button>
        </div>

        {/* Cards grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {transactions.map(txn => (
            <QuoteCard key={txn.transaction_id} txn={txn} />
          ))}
        </div>
      </div>
    </div>
  )
}
