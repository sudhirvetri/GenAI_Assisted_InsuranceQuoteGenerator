import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Navbar() {
  const { token, logout } = useAuth()

  return (
    <nav className="bg-white shadow-sm border-b border-gray-100">
      <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2">
          <div className="w-8 h-8 bg-teal-600 rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-sm">SC</span>
          </div>
          <span className="font-bold text-gray-900 text-lg">SwiftCare</span>
        </Link>
        <div className="flex items-center gap-4">
          {token ? (
            <button
              onClick={logout}
              className="text-sm text-gray-500 hover:text-gray-700 transition-colors"
            >
              Sign Out
            </button>
          ) : (
            <span className="text-sm text-teal-600 font-medium">Health Insurance</span>
          )}
        </div>
      </div>
    </nav>
  )
}
