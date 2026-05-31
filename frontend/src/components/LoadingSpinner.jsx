export default function LoadingSpinner({ message = 'Loading...' }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4">
      <div className="w-12 h-12 border-4 border-teal-200 border-t-teal-600 rounded-full animate-spin" />
      {message && <p className="text-gray-600 text-sm">{message}</p>}
    </div>
  )
}
