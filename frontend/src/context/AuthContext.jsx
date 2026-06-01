import { createContext, useContext, useState } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null)
  const [userId, setUserId] = useState(null)

  function login(idToken, sub) {
    setToken(idToken)
    setUserId(sub)
  }

  function logout() {
    setToken(null)
    setUserId(null)
    // Sign out from Cognito hosted UI and redirect to landing page
    const cognitoDomain = 'https://iqg-auth-867344470917.auth.us-east-1.amazoncognito.com'
    const clientId = '56ilueodgm4jmccvb5l9bjj47l'
    const logoutUri = encodeURIComponent('https://dtqht50eixzia.cloudfront.net')
    window.location.href = `${cognitoDomain}/logout?client_id=${clientId}&logout_uri=${logoutUri}`
  }

  return (
    <AuthContext.Provider value={{ token, userId, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
