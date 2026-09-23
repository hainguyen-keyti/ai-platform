import { useState } from 'react'
import { api, setToken } from '../lib/api.js'

export default function Login({ onSignedIn }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [invite, setInvite] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mode === 'register') {
        await api.register(email, password, name || null, invite)
      }
      const session = await api.login(email, password)
      setToken(session.token)
      onSignedIn(session.user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center bg-slate-100 p-6">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-xl shadow p-6 space-y-4">
        <h1 className="text-xl font-semibold">AI Platform</h1>

        <div className="flex gap-2 text-sm">
          <button type="button" onClick={() => setMode('login')}
            className={`px-3 py-1 rounded ${mode === 'login' ? 'bg-slate-900 text-white' : 'bg-slate-100'}`}>
            Sign in
          </button>
          <button type="button" onClick={() => setMode('register')}
            className={`px-3 py-1 rounded ${mode === 'register' ? 'bg-slate-900 text-white' : 'bg-slate-100'}`}>
            Create account
          </button>
        </div>

        <input className="w-full border rounded px-3 py-2" type="email" required placeholder="email"
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="w-full border rounded px-3 py-2" type="password" required minLength={8}
          placeholder="password" value={password} onChange={(e) => setPassword(e.target.value)} />

        {mode === 'register' && (
          <>
            <input className="w-full border rounded px-3 py-2" placeholder="name (optional)"
              value={name} onChange={(e) => setName(e.target.value)} />
            <input className="w-full border rounded px-3 py-2" required placeholder="invite code"
              value={invite} onChange={(e) => setInvite(e.target.value)} />
          </>
        )}

        {error && <div className="text-sm text-red-600">{error}</div>}

        <button type="submit" disabled={busy}
          className="w-full bg-slate-900 text-white rounded py-2 disabled:opacity-50">
          {busy ? 'working...' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>
      </form>
    </div>
  )
}
