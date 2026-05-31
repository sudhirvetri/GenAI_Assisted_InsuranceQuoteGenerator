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
            <a
              href={SIGN_IN_URL}
              className="inline-block bg-amber-400 hover:bg-amber-300 text-gray-900 font-bold text-lg px-10 py-4 rounded-xl shadow-lg hover:shadow-xl transition-all transform hover:-translate-y-0.5"
            >
              Get My Quote →
            </a>
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
