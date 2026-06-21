import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'

// After ECS migration, /quotes/submit goes to ALB; other routes stay on API Gateway
const API_BASE_ALB = 'http://REPLACE_WITH_ALB_DNS_AFTER_DEPLOY'
const API_BASE     = 'https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1'

const SUM_INSURED_OPTIONS = [
  { label: '₹3,00,000', value: 300000 },
  { label: '₹5,00,000', value: 500000 },
  { label: '₹7,50,000', value: 750000 },
  { label: '₹10,00,000', value: 1000000 },
  { label: '₹15,00,000', value: 1500000 },
  { label: '₹20,00,000', value: 2000000 },
  { label: '₹30,00,000', value: 3000000 },
  { label: '₹50,00,000', value: 5000000 },
]

const BUDGET_OPTIONS = [
  { label: 'Up to ₹10,000', value: 10000 },
  { label: 'Up to ₹15,000', value: 15000 },
  { label: 'Up to ₹20,000', value: 20000 },
  { label: 'Up to ₹25,000', value: 25000 },
  { label: 'Up to ₹30,000', value: 30000 },
  { label: 'Up to ₹50,000', value: 50000 },
  { label: '₹1,00,000+', value: 100000 },
]

const LIFESTYLE_OPTIONS = [
  'Maternity Cover',
  'Annual Health Checkup',
  'Teleconsultation',
  'Critical Illness Cover',
  'AYUSH Treatment',
  'Daycare Procedures',
  'Ambulance Cover',
  'Restoration Benefit',
]

const CONDITION_OPTIONS = ['Diabetes', 'Hypertension', 'Heart Disease', 'Asthma', 'None']

const FAMILY_COMPOSITION_OPTIONS = [
  { value: 'self', label: 'Self only' },
  { value: 'self_spouse', label: 'Self + Spouse' },
  { value: 'self_spouse_children', label: 'Self + Spouse + Children' },
  { value: 'self_parents', label: 'Self + Parents' },
  { value: 'self_spouse_children_parents', label: 'Self + Spouse + Children + Parents' },
]

const DEFAULT_FORM = {
  category: 'individual',
  age: '',
  family_composition: 'self',
  email: '',
  sum_insured: '',
  budget: '',
  lifestyle_priorities: [],
  pre_existing_conditions: [],
  consent: false,
}

function toggleItem(arr, item) {
  return arr.includes(item) ? arr.filter(i => i !== item) : [...arr, item]
}

export default function QuoteForm() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState(DEFAULT_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="text-gray-600 mb-4">You need to sign in first.</p>
          <a href="/" className="text-teal-600 font-semibold hover:underline">Go to Home</a>
        </div>
      </div>
    )
  }

  function set(field, value) {
    setForm(prev => ({ ...prev, [field]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.consent) {
      setError('Please accept the IRDAI disclosure to proceed.')
      return
    }
    setError(null)
    setSubmitting(true)

    const mapLifestyle = (p) => p.toLowerCase()
      .replace('maternity cover', 'maternity')
      .replace('annual health checkup', 'annual_checkup')
      .replace('teleconsultation', 'teleconsult')
      .replace('critical illness cover', 'critical_illness')
      .replace('ayush treatment', 'ayush')
      .replace('daycare procedures', 'daycare')
      .replace('ambulance cover', 'ambulance')
      .replace(/ /g, '_')

    const payload = {
      user: {
        category: form.category === 'senior_citizen' ? 'senior' : form.category,
        age: parseInt(form.age, 10),
        email: form.email,
        family_composition: form.family_composition || 'self',
      },
      preferences: {
        target_sum_insured: parseInt(form.sum_insured),
        budget_annual_premium_inr: parseInt(form.budget),
        lifestyle_priorities: form.lifestyle_priorities.map(mapLifestyle),
        pre_existing_conditions: form.pre_existing_conditions
          .filter(c => c !== 'None')
          .map(c => c.toLowerCase().replace(/ /g, '_')),
      },
      consent: {
        irdai_disclosure_ack: true,
        ack_timestamp: new Date().toISOString(),
      },
    }
    if (false) {
      // family_composition already included above
    }

    try {
      const res = await fetch(`${API_BASE_ALB}/v1/quotes/submit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.message || `Submission failed (${res.status})`)
      }

      const data = await res.json()
      const txId = data.transaction_id || data.transactionId
      navigate(`/results/${txId}`)
    } catch (err) {
      setError(err.message || 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />

      <main className="flex-1 py-10 px-4">
        <div className="max-w-2xl mx-auto">
          <div className="mb-8 text-center">
            <h1 className="text-3xl font-extrabold text-gray-900">Tell Us About Yourself</h1>
            <p className="text-gray-500 mt-2">We'll use this to find the best plans for you</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-8">
            {/* About You */}
            <section className="bg-white rounded-xl shadow-sm p-6">
              <h2 className="text-lg font-bold text-gray-900 mb-6 flex items-center gap-2">
                <span className="w-7 h-7 bg-teal-100 text-teal-700 rounded-full flex items-center justify-center text-sm font-bold">1</span>
                About You
              </h2>

              <div className="space-y-5">
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">Category</label>
                  <div className="flex gap-4">
                    {['individual', 'family', 'senior_citizen'].map(cat => (
                      <label key={cat} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          name="category"
                          value={cat}
                          checked={form.category === cat}
                          onChange={() => set('category', cat)}
                          className="text-teal-600 w-4 h-4 accent-teal-600"
                        />
                        <span className="text-sm text-gray-700 capitalize">
                          {cat === 'senior_citizen' ? 'Senior Citizen' : cat.charAt(0).toUpperCase() + cat.slice(1)}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-1">
                    Age <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="number"
                    min="18"
                    max="99"
                    required
                    value={form.age}
                    onChange={e => set('age', e.target.value)}
                    placeholder="Enter your age"
                    className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                  />
                </div>

                {form.category === 'family' && (
                  <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-1">
                      Family Composition <span className="text-red-500">*</span>
                    </label>
                    <select
                      required
                      value={form.family_composition}
                      onChange={e => set('family_composition', e.target.value)}
                      className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white"
                    >
                      {FAMILY_COMPOSITION_OPTIONS.map(o => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </div>
                )}

                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-1">
                    Email <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="email"
                    required
                    value={form.email}
                    onChange={e => set('email', e.target.value)}
                    placeholder="you@example.com"
                    className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                  />
                </div>
              </div>
            </section>

            {/* Coverage Preferences */}
            <section className="bg-white rounded-xl shadow-sm p-6">
              <h2 className="text-lg font-bold text-gray-900 mb-6 flex items-center gap-2">
                <span className="w-7 h-7 bg-teal-100 text-teal-700 rounded-full flex items-center justify-center text-sm font-bold">2</span>
                Coverage Preferences
              </h2>

              <div className="space-y-5">
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-1">
                    Target Sum Insured <span className="text-red-500">*</span>
                  </label>
                  <select
                    required
                    value={form.sum_insured}
                    onChange={e => set('sum_insured', Number(e.target.value))}
                    className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white"
                  >
                    <option value="">Select coverage amount</option>
                    {SUM_INSURED_OPTIONS.map(o => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-1">
                    Annual Budget for Premium <span className="text-red-500">*</span>
                  </label>
                  <select
                    required
                    value={form.budget}
                    onChange={e => set('budget', Number(e.target.value))}
                    className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white"
                  >
                    <option value="">Select your budget</option>
                    {BUDGET_OPTIONS.map(o => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Lifestyle Priorities
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {LIFESTYLE_OPTIONS.map(item => (
                      <label key={item} className="flex items-center gap-2 cursor-pointer group">
                        <input
                          type="checkbox"
                          checked={form.lifestyle_priorities.includes(item)}
                          onChange={() =>
                            set('lifestyle_priorities', toggleItem(form.lifestyle_priorities, item))
                          }
                          className="w-4 h-4 accent-teal-600 rounded"
                        />
                        <span className="text-sm text-gray-700 group-hover:text-gray-900">{item}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Pre-existing Conditions
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {CONDITION_OPTIONS.map(item => (
                      <label key={item} className="flex items-center gap-2 cursor-pointer group">
                        <input
                          type="checkbox"
                          checked={form.pre_existing_conditions.includes(item)}
                          onChange={() =>
                            set(
                              'pre_existing_conditions',
                              toggleItem(form.pre_existing_conditions, item),
                            )
                          }
                          className="w-4 h-4 accent-teal-600 rounded"
                        />
                        <span className="text-sm text-gray-700 group-hover:text-gray-900">{item}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            {/* Consent */}
            <section className="bg-white rounded-xl shadow-sm p-6">
              <h2 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                <span className="w-7 h-7 bg-teal-100 text-teal-700 rounded-full flex items-center justify-center text-sm font-bold">3</span>
                Consent
              </h2>
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.consent}
                  onChange={e => set('consent', e.target.checked)}
                  className="w-4 h-4 mt-0.5 accent-teal-600 flex-shrink-0"
                />
                <span className="text-sm text-gray-700 leading-relaxed">
                  I acknowledge the IRDAI disclosure and consent to processing my health information
                  for insurance quote generation.
                </span>
              </label>
            </section>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-teal-600 hover:bg-teal-700 disabled:bg-teal-300 text-white font-bold py-4 rounded-xl text-lg transition-colors shadow-md"
            >
              {submitting ? 'Submitting...' : 'Generate My Quote →'}
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
