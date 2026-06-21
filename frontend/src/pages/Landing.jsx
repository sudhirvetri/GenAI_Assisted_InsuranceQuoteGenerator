import Navbar from '../components/Navbar'

const COGNITO_DOMAIN = 'https://iqg-auth-867344470917.auth.us-east-1.amazoncognito.com'
const CLIENT_ID = '56ilueodgm4jmccvb5l9bjj47l'
const REDIRECT_URI = 'https://dtqht50eixzia.cloudfront.net/callback'

const SIGN_IN_URL =
  `${COGNITO_DOMAIN}/login` +
  `?client_id=${CLIENT_ID}` +
  `&response_type=code` +
  `&scope=email+openid+profile` +
  `&redirect_uri=${encodeURIComponent(REDIRECT_URI)}`

const GOOGLE_LOGIN_URL =
  'https://iqg-auth-867344470917.auth.us-east-1.amazoncognito.com/oauth2/authorize?' +
  'identity_provider=Google&' +
  'response_type=code&' +
  'client_id=56ilueodgm4jmccvb5l9bjj47l&' +
  'redirect_uri=https%3A%2F%2Fdtqht50eixzia.cloudfront.net%2Fcallback&' +
  'scope=email+profile+openid'

export default function Landing() {
  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col">
        {/* Hero */}
        <section className="bg-gradient-to-br from-teal-600 via-teal-700 to-blue-700 text-white py-24 px-4">
          <div className="max-w-4xl mx-auto text-center">
            <div className="inline-flex items-center gap-2 bg-white/20 rounded-full px-4 py-1.5 text-sm font-medium mb-8">
              <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
              AI-Powered Insurance Recommendations
            </div>
            <h1 className="text-4xl md:text-6xl font-extrabold leading-tight mb-6">
              Get Your Personalized<br />
              <span className="text-amber-300">Health Insurance Quote</span><br />
              in Seconds
            </h1>
            <p className="text-xl text-teal-100 mb-10 max-w-2xl mx-auto">
              AI-powered recommendations tailored to your needs. Compare 30+ plans
              and find the perfect coverage for you and your family.
            </p>
            <div className="flex flex-col items-center max-w-sm mx-auto">
              <a
                href={SIGN_IN_URL}
                className="w-full text-center bg-amber-400 hover:bg-amber-300 text-gray-900 font-bold text-lg px-10 py-4 rounded-xl shadow-lg hover:shadow-xl transition-all transform hover:-translate-y-0.5"
              >
                Get My Quote →
              </a>
              <div className="flex items-center gap-3 my-3 w-full">
                <div className="flex-1 h-px bg-white/30"></div>
                <span className="text-xs text-white/60 font-medium">OR</span>
                <div className="flex-1 h-px bg-white/30"></div>
              </div>
              <a
                href={GOOGLE_LOGIN_URL}
                onClick={(e) =>
                {
                  e.preventDefault()
                  window.location.href = GOOGLE_LOGIN_URL
                }}
                className="flex items-center justify-center gap-3 w-full bg-white border-2 border-gray-200 hover:border-gray-300 hover:bg-gray-50 text-gray-700 font-semibold py-3 px-6 rounded-xl transition-all shadow-sm"
              >
                <svg width="20" height="20" viewBox="0 0 48 48">
                  <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.08 17.74 9.5 24 9.5z" />
                  <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
                  <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
                  <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-3.59-13.46-8.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
                  <path fill="none" d="M0 0h48v48H0z" />
                </svg>
                Continue with Google
              </a>
            </div>
            <p className="text-teal-200 text-sm mt-4">Free • No commitment • Takes 2 minutes</p>
          </div>
        </section>

        {/* Features */}
        <section className="py-16 px-4">
          <div className="max-w-5xl mx-auto">
            <h2 className="text-2xl font-bold text-center text-gray-800 mb-12">
              Why choose SwiftCare?
            </h2>
            <div className="grid md:grid-cols-3 gap-8">
              {[
                {
                  icon: '🤖',
                  title: 'AI-Powered Matching',
                  desc: 'Our AI analyzes 30+ insurance plans to find the best fit for your unique health profile and budget.',
                },
                {
                  icon: '⚡',
                  title: 'Instant Results',
                  desc: 'Get your top 3 personalized recommendations in under 30 seconds — no phone calls, no waiting.',
                },
                {
                  icon: '🔒',
                  title: 'IRDAI Compliant',
                  desc: 'All plans are from IRDAI-approved insurers. Your data is protected and never shared without consent.',
                },
              ].map(f => (
                <div key={f.title} className="bg-white rounded-xl p-6 shadow-sm text-center">
                  <div className="text-4xl mb-4">{f.icon}</div>
                  <h3 className="font-bold text-gray-900 mb-2">{f.title}</h3>
                  <p className="text-gray-500 text-sm leading-relaxed">{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA Banner */}
        <section className="bg-blue-600 py-14 px-4 text-center text-white">
          <h2 className="text-3xl font-bold mb-4">Ready to find your perfect plan?</h2>
          <p className="text-blue-100 mb-8">Join thousands who found better coverage at lower premiums.</p>
          <a
            href={SIGN_IN_URL}
            className="inline-block bg-white text-blue-600 font-bold px-10 py-4 rounded-xl hover:bg-blue-50 transition-colors"
          >
            Get My Free Quote
          </a>
        </section>
      </main>

      <footer className="bg-gray-800 text-gray-400 text-sm py-6 px-4 text-center">
        <p>© 2025 SwiftCare Health Insurance. All rights reserved.</p>
        <p className="mt-1">IRDAI Registration No. 12345 | CIN: U74999MH2025PLC000000</p>
      </footer>
    </div>
  )
}
