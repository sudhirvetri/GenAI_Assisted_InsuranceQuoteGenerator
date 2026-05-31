import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import LoadingSpinner from '../components/LoadingSpinner'

const API_BASE = 'https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1'
const COGNITO_DOMAIN = 'https://iqg-auth-867344470917.auth.us-east-1.amazoncognito.com'
const CLIENT_ID = '56ilueodgm4jmccvb5l9bjj47l'
const REDIRECT_URI = 'https://dtqht50eixzia.cloudfront.net/callback'

export default function Callback() {
  const [searchParams] = useSearchParams()
  const { login } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const exchanged = useRef(false)

  useEffect(() => {
    if (exchanged.current) return
    exchanged.current = true

    const code = searchParams.get('code')
    if (!code) {
      setError('No authorization code found. Please try signing in again.')
      return
    }

    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: REDIRECT_URI,
      client_id: CLIENT_ID,
    })

    fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    })
      .then(async res => {
        if (!res.ok) {
          const text = await res.text()
          throw new Error(text || `Token exchange failed (${res.status})`)
        }
        return res.json()
      })
      .then(data => {
        const idToken = data.id_token
        let sub = null
        try {
          const payload = JSON.parse(atob(idToken.split('.')[1]))
          sub = payload.sub
        } catch {
          // sub extraction is best-effort
        }
        login(idToken, sub)
        return fetch(`${API_BASE}/my-quotes`, {
          headers: { Authorization: `Bearer ${idToken}` },
        })
          .then(res => res.ok ? res.json() : { count: 0 })
          .then(data => {
            navigate(data.count > 0 ? '/my-quotes' : '/quote-form', { replace: true })
          })
          .catch(() => {
            navigate('/quote-form', { replace: true })
          })
      })
      .catch(err => {
        setError(err.message || 'Authentication failed. Please try again.')
      })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="bg-white rounded-xl shadow-md p-8 max-w-md w-full text-center">
          <div className="text-4xl mb-4">⚠️</div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Sign-in Failed</h2>
          <p className="text-gray-500 text-sm mb-6">{error}</p>
          <a
            href="/"
            className="inline-block bg-teal-600 hover:bg-teal-700 text-white font-semibold px-6 py-3 rounded-lg transition-colors"
          >
            Try Again
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <LoadingSpinner message="Signing you in..." />
      </div>
    </div>
  )
}
