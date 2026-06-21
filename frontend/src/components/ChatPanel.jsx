import { useState, useRef, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { useWebSocket } from '../context/WebSocketContext'

function renderInline(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/)
  return parts.map((part, i) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={i}>{part.slice(2, -2)}</strong>
      : part
  )
}

function renderTable(lines) {
  const dataRows = lines.filter(l => !l.match(/^\|[\s:-]+\|/))
  const parsed = dataRows.map(row =>
    row.split('|').filter((_, i, a) => i > 0 && i < a.length - 1).map(c => c.trim())
  )
  if (!parsed.length) return null
  const [header, ...body] = parsed
  return (
    <div className="overflow-x-auto mb-2">
      <table className="text-xs border-collapse w-full">
        <thead>
          <tr>
            {header.map((h, i) => (
              <th key={i} className="border border-gray-300 bg-gray-100 px-2 py-1 text-left font-semibold">
                {renderInline(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? '' : 'bg-gray-50'}>
              {row.map((cell, ci) => (
                <td key={ci} className="border border-gray-300 px-2 py-1">
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function renderMarkdown(text) {
  const blocks = text.split(/\n\n+/)
  return (
    <>
      {blocks.map((block, blockIdx) => {
        const lines = block.split('\n')
        if (lines[0]?.trim().startsWith('|')) {
          return <div key={blockIdx}>{renderTable(lines)}</div>
        }
        if (lines.length > 0 && lines.every(l => /^[-*]\s/.test(l))) {
          return (
            <ul key={blockIdx} className="list-disc list-inside space-y-0.5 mb-2 text-sm">
              {lines.map((line, i) => (
                <li key={i}>{renderInline(line.replace(/^[-*]\s+/, ''))}</li>
              ))}
            </ul>
          )
        }
        return (
          <div key={blockIdx} className="mb-2">
            {lines.map((line, lineIdx) => {
              if (line.startsWith('### ')) return <h4 key={lineIdx} className="font-semibold text-gray-800 mt-2 mb-1 text-sm">{renderInline(line.slice(4))}</h4>
              if (line.startsWith('## ')) return <h3 key={lineIdx} className="font-bold text-gray-900 mt-3 mb-1 text-sm">{renderInline(line.slice(3))}</h3>
              if (/^[-*]\s/.test(line)) return <ul key={lineIdx} className="list-disc list-inside text-sm"><li>{renderInline(line.replace(/^[-*]\s+/, ''))}</li></ul>
              if (!line.trim()) return null
              return <p key={lineIdx} className="text-sm">{renderInline(line)}</p>
            })}
          </div>
        )
      })}
    </>
  )
}

export default function ChatPanel({ transactionId }) {
  const { token } = useAuth()
  const { sendMessage, addHandler, removeHandler, wsReady } = useWebSocket()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamingTurnId, setStreamingTurnId] = useState(null)
  const bottomRef = useRef(null)
  const currentTurnRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Handle incoming chat_chunk frames from WebSocket
  const handleChatChunk = useCallback((data) => {
    if (data.turn_id !== currentTurnRef.current) return

    if (!data.final) {
      // Append delta to the streaming message
      setMessages(prev => {
        const last = prev[prev.length - 1]
        if (last?.role === 'assistant' && last?.streaming) {
          return [
            ...prev.slice(0, -1),
            { ...last, content: last.content + data.delta }
          ]
        }
        // First chunk — create the streaming message bubble
        return [...prev, { role: 'assistant', content: data.delta, streaming: true }]
      })
    } else {
      // Final frame — mark message as complete
      setMessages(prev => {
        const last = prev[prev.length - 1]
        if (last?.role === 'assistant' && last?.streaming) {
          return [...prev.slice(0, -1), { ...last, streaming: false }]
        }
        return prev
      })
      setStreaming(false)
      setStreamingTurnId(null)
      currentTurnRef.current = null
    }
  }, [])

  const handleWsError = useCallback((data) => {
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: data.message || 'Sorry, something went wrong.',
      streaming: false,
    }])
    setStreaming(false)
    currentTurnRef.current = null
  }, [])

  useEffect(() => {
    addHandler('chat_chunk', handleChatChunk)
    addHandler('error', handleWsError)
    return () => {
      removeHandler('chat_chunk', handleChatChunk)
      removeHandler('error', handleWsError)
    }
  }, [addHandler, removeHandler, handleChatChunk, handleWsError])

  async function sendChat() {
    const text = input.trim()
    if (!text || streaming) return

    const turnId = String(Date.now())
    currentTurnRef.current = turnId

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setStreaming(true)
    setStreamingTurnId(turnId)

    const sent = sendMessage({
      action: 'sendMessage',
      transaction_id: transactionId,
      message: text,
      turn_id: turnId,
    })

    if (!sent) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Connection lost. Please refresh the page.',
        streaming: false,
      }])
      setStreaming(false)
      currentTurnRef.current = null
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendChat()
    }
  }

  return (
    <div className="bg-white rounded-xl shadow-md p-6">
      <h2 className="text-xl font-bold text-gray-900 mb-1">
        Have questions about your recommendations?
      </h2>
      <p className="text-sm text-gray-500 mb-4">
        Ask our AI anything about these plans
        {wsReady && <span className="ml-2 text-teal-600 text-xs">⚡ Live</span>}
      </p>

      <div className="border border-gray-200 rounded-lg h-64 overflow-y-auto p-4 mb-4 flex flex-col gap-3 bg-gray-50">
        {messages.length === 0 && (
          <p className="text-sm text-gray-400 text-center mt-8">
            Ask a question to get started...
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'user' ? (
              <div className="max-w-[80%] rounded-2xl rounded-br-sm px-4 py-2 text-sm leading-relaxed bg-teal-600 text-white">
                {msg.content}
              </div>
            ) : (
              <div className="max-w-[90%] rounded-2xl rounded-bl-sm px-4 py-3 bg-white border border-gray-200 shadow-sm text-gray-800">
                {renderMarkdown(msg.content)}
                {msg.streaming && (
                  <span className="inline-block w-1 h-4 bg-teal-500 animate-pulse ml-0.5 align-middle" />
                )}
              </div>
            )}
          </div>
        ))}
        {streaming && messages[messages.length - 1]?.role !== 'assistant' && (
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
          disabled={streaming}
          className="flex-1 border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:bg-gray-100"
        />
        <button
          onClick={sendChat}
          disabled={streaming || !input.trim()}
          className="bg-teal-600 hover:bg-teal-700 disabled:bg-teal-300 text-white font-semibold px-5 py-2 rounded-lg transition-colors text-sm"
        >
          Send
        </button>
      </div>
    </div>
  )
}
