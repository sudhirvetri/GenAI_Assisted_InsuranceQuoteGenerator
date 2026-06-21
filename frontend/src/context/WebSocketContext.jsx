/**
 * WebSocket context — manages a single persistent WebSocket connection.
 * Opens on sign-in, closes on sign-out.
 * Exposes:
 *   - wsRef: the WebSocket instance
 *   - connectionId: the connection ID assigned by the server (sent as first message)
 *   - addHandler(type, fn): register a message handler for a message type
 *   - removeHandler(type, fn): unregister a handler
 *   - sendMessage(data): send a JSON frame
 */

import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import { useAuth } from './AuthContext'

// Replace with actual WsApiUrl from CDK output after deploy
const WS_URL = 'wss://s7631o60d8.execute-api.us-east-1.amazonaws.com/v1'

const WebSocketContext = createContext(null)

export function WebSocketProvider({ children }) {
  const { token } = useAuth()
  const wsRef = useRef(null)
  const [connectionId, setConnectionId] = useState(null)
  const [wsReady, setWsReady] = useState(false)
  const handlersRef = useRef({})  // { messageType: Set<fn> }

  const addHandler = useCallback((type, fn) => {
    if (!handlersRef.current[type]) handlersRef.current[type] = new Set()
    handlersRef.current[type].add(fn)
  }, [])

  const removeHandler = useCallback((type, fn) => {
    handlersRef.current[type]?.delete(fn)
  }, [])

  const sendMessage = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
      return true
    }
    return false
  }, [])

  useEffect(() => {
    if (!token) {
      // Sign out — close WebSocket
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
        setConnectionId(null)
        setWsReady(false)
      }
      return
    }

    // Open WebSocket with JWT in the protocol header
    const ws = new WebSocket(`${WS_URL}?token=${token}`)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('WebSocket connected')
      setWsReady(true)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        // First message from server contains connection_id
        if (data.type === 'connected' && data.connection_id) {
          setConnectionId(data.connection_id)
        }

        // Dispatch to registered handlers by type
        const handlers = handlersRef.current[data.type]
        if (handlers) {
          handlers.forEach(fn => fn(data))
        }

        // Also dispatch to wildcard handlers
        const wildcards = handlersRef.current['*']
        if (wildcards) {
          wildcards.forEach(fn => fn(data))
        }
      } catch (err) {
        console.error('WebSocket message parse error:', err)
      }
    }

    ws.onerror = (err) => {
      console.error('WebSocket error:', err)
    }

    ws.onclose = () => {
      console.log('WebSocket closed')
      setWsReady(false)
      setConnectionId(null)
    }

    return () => {
      ws.close()
    }
  }, [token])

  return (
    <WebSocketContext.Provider value={{ wsRef, connectionId, wsReady, addHandler, removeHandler, sendMessage }}>
      {children}
    </WebSocketContext.Provider>
  )
}

export function useWebSocket() {
  const ctx = useContext(WebSocketContext)
  if (!ctx) throw new Error('useWebSocket must be used within WebSocketProvider')
  return ctx
}
