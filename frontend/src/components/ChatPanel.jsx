import { useState, useRef, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'

const API_BASE = 'https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1'

export default function ChatPanel({ transactionId }) {
  const { token } = useAuth()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage() {
    const text = input.trim()
    if (!text || loading) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ transaction_id: transactionId, message: text }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const reply = data.response || data.message || 'Sorry, I could not process that.'
      setMessages(prev => [...prev, { role: 'assistant', content: reply }])
    } catch {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' },
      ])
    } finally {
      setLoading(false)
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="bg-white rounded-xl shadow-md p-6">
      <h2 className="text-xl font-bold text-gray-900 mb-1">
        Have questions about your recommendations?
      </h2>
      <p className="text-sm text-gray-500 mb-4">Ask our AI anything about these plans</p>

      <div className="border border-gray-200 rounded-lg h-64 overflow-y-auto p-4 mb-4 flex flex-col gap-3 bg-gray-50">
        {messages.length === 0 && (
          <p className="text-sm text-gray-400 text-center mt-8">
            Ask a question to get started...
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-teal-600 text-white rounded-br-sm'
                  : 'bg-white text-gray-800 border border-gray-200 rounded-bl-sm shadow-sm'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-2 shadow-sm">
              <div className="flex gap-1 items-center">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask about your plans..."
          disabled={loading}
          className="flex-1 border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:bg-gray-100"
        />
        <button
          onClick={sendMessage}
          disabled={loading || !input.trim()}
          className="bg-teal-600 hover:bg-teal-700 disabled:bg-teal-300 text-white font-semibold px-5 py-2 rounded-lg transition-colors text-sm"
        >
          Send
        </button>
      </div>
    </div>
  )
}
