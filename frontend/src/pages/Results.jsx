import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useWebSocket } from '../context/WebSocketContext'
import Navbar from '../components/Navbar'
import PlanCard from '../components/PlanCard'
import ChatPanel from '../components/ChatPanel'
import LoadingSpinner from '../components/LoadingSpinner'

const API_BASE = 'https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1'
const POLL_INTERVAL = 3000
const MAX_POLL_SECONDS = 30

export default function Results() {
  const { transactionId } = useParams()
  const { token } = useAuth()
  const { addHandler, removeHandler, wsReady } = useWebSocket()
  const navigate = useNavigate()

  const [status, setStatus] = useState('PENDING')
  const [recommendations, setRecommendations] = useState([])
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [source, setSource] = useState('websocket') // 'websocket' or 'polling'
  const pollRef = useRef(null)
  const wsReceivedRef = useRef(false)
  const startTime = useRef(Date.now())

  // Elapsed timer
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.current) / 1000))
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  // WebSocket handler — receives quote_complete push from quote_worker
  const handleQuoteComplete = useCallback((data) => {
    if (data.transaction_id !== transactionId) return
    wsReceivedRef.current = true
    clearInterval(pollRef.current)
    setRecommendations(data.recommendations || [])
    setStatus('COMPLETE')
  }, [transactionId])

  // Register WebSocket handler
  useEffect(() => {
    addHandler('quote_complete', handleQuoteComplete)
    return () => removeHandler('quote_complete', handleQuoteComplete)
  }, [addHandler, removeHandler, handleQuoteComplete])

  // Polling fallback — starts after 2s but yields to WebSocket
  useEffect(() => {
    if (!token) return

    async function poll() {
      // If WebSocket already delivered the result, stop polling
      if (wsReceivedRef.current) {
        clearInterval(pollRef.current)
        return
      }
      // Stop polling after MAX_POLL_SECONDS
      if (Math.floor((Date.now() - startTime.current) / 1000) > MAX_POLL_SECONDS) {
        clearInterval(pollRef.current)
        setError('Quote generation timed out. Please try again.')
        setStatus('FAILED')
        return
      }

      try {
        const res = await fetch(`${API_BASE}/quotes/${transactionId}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()

        if (data.status === 'COMPLETE' || data.status === 'COMPLETED') {
          if (!wsReceivedRef.current) {
            clearInterval(pollRef.current)
            setSource('polling')
            setRecommendations(data.recommendations || [])
            setStatus('COMPLETE')
          }
        } else if (data.status === 'FAILED' || data.status === 'ERROR') {
          clearInterval(pollRef.current)
          setError('Quote generation failed. Please try again.')
          setStatus('FAILED')
        }
      } catch (err) {
        clearInterval(pollRef.current)
        setError(err.message || 'Failed to fetch results.')
        setStatus('FAILED')
      }
    }

    // Start polling after 2 seconds (give WebSocket a chance to deliver first)
    const startDelay = setTimeout(() => {
      pollRef.current = setInterval(poll, POLL_INTERVAL)
    }, 2000)

    return () => {
      clearTimeout(startDelay)
      clearInterval(pollRef.current)
    }
  }, [transactionId, token])

  function handleSelectPlan(plan) {
    navigate('/confirmed', { state: { plan, transactionId } })
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-600">
          Please <a href="/" className="text-teal-600 underline">sign in</a> to view your results.
        </p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex flex-col bg-gray-50">
        <Navbar />
        <div className="flex-1 flex items-center justify-center px-4">
          <div className="bg-white rounded-xl shadow-md p-8 max-w-md w-full text-center">
            <div className="text-4xl mb-4">😔</div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">Something went wrong</h2>
            <p className="text-gray-500 text-sm mb-6">{error}</p>
            <button
              onClick={() => navigate('/quote-form')}
              className="bg-teal-600 hover:bg-teal-700 text-white font-semibold px-6 py-3 rounded-lg transition-colors"
            >
              Try Again
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (status === 'PENDING') {
    return (
      <div className="min-h-screen flex flex-col bg-gray-50">
        <Navbar />
        <div className="flex-1 flex items-center justify-center px-4">
          <div className="text-center max-w-sm">
            <div className="mb-6">
              <div className="w-20 h-20 bg-teal-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <div className="w-12 h-12 border-4 border-teal-200 border-t-teal-600 rounded-full animate-spin" />
              </div>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 mb-3">Analyzing Your Profile</h2>
            <p className="text-gray-500 mb-4">
              Our AI is analyzing 30+ plans to find your best matches...
            </p>
            <div className="inline-flex items-center gap-2 bg-teal-50 text-teal-700 px-4 py-2 rounded-full text-sm font-medium">
              <span className="w-2 h-2 bg-teal-500 rounded-full animate-pulse" />
              {wsReady ? '⚡ Live streaming' : '🔄 Connecting...'} · {elapsed}s
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <Navbar />
      <main className="flex-1 py-10 px-4">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-10">
            <h1 className="text-3xl font-extrabold text-gray-900">
              Your Personalized Recommendations
            </h1>
            <p className="text-gray-500 mt-2">
              Based on your profile, our AI recommends these top 3 plans
            </p>
          </div>

          {recommendations.length === 0 ? (
            <div className="text-center text-gray-500 py-12">
              No recommendations found. Please try again.
            </div>
          ) : (
            <div className="grid md:grid-cols-3 gap-6 mb-10">
              {recommendations.map((plan, i) => (
                <PlanCard key={plan.plan_id || i} plan={plan} onSelect={handleSelectPlan} />
              ))}
            </div>
          )}

          <ChatPanel transactionId={transactionId} />
        </div>
      </main>
    </div>
  )
}
