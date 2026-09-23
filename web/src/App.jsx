import { useEffect, useState } from 'react'
import { api, getToken, setToken } from './lib/api.js'
import Login from './pages/Login.jsx'
import Chat from './pages/Chat.jsx'
import Gallery from './pages/Gallery.jsx'

export default function App() {
  const [user, setUser] = useState(null)
  const [view, setView] = useState('chat')
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    if (!getToken()) { setChecking(false); return }
    api.me().then(setUser).catch(() => setToken(null)).finally(() => setChecking(false))
  }, [])

  function signOut() {
    setToken(null)
    setUser(null)
  }

  if (checking) return <div className="p-6 text-sm text-slate-500">loading...</div>
  if (!user) return <Login onSignedIn={setUser} />

  return (
    <div className="flex flex-col h-full">
      <nav className="flex items-center gap-4 border-b bg-white px-4 py-2 text-sm">
        <span className="font-semibold">AI Platform</span>
        {['chat', 'gallery'].map((v) => (
          <button key={v} onClick={() => setView(v)}
            className={view === v ? 'font-medium underline' : 'text-slate-500'}>
            {v}
          </button>
        ))}
        <span className="ml-auto text-slate-500">
          {user.email} · {user.quota_remaining} left
        </span>
        <button onClick={signOut} className="text-slate-500 hover:underline">sign out</button>
      </nav>
      <main className="flex-1 min-h-0">
        {view === 'chat'
          ? <Chat onQuotaSpent={() => api.me().then(setUser).catch(() => {})} />
          : <Gallery />}
      </main>
    </div>
  )
}
