import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { WebSocketProvider } from './context/WebSocketContext'
import Landing from './pages/Landing'
import Callback from './pages/Callback'
import QuoteForm from './pages/QuoteForm'
import Results from './pages/Results'
import Confirmed from './pages/Confirmed'
import MyQuotes from './pages/MyQuotes'

export default function App() {
  return (
    <AuthProvider>
      <WebSocketProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/callback" element={<Callback />} />
            <Route path="/quote-form" element={<QuoteForm />} />
            <Route path="/results/:transactionId" element={<Results />} />
            <Route path="/confirmed" element={<Confirmed />} />
            <Route path="/my-quotes" element={<MyQuotes />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </WebSocketProvider>
    </AuthProvider>
  )
}
