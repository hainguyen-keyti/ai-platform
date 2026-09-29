import { useEffect, useState } from 'react'
import { api, getToken, setToken } from './lib/api.js'
import { LanguageProvider, useStrings } from './lib/strings.jsx'
import Login from './pages/Login.jsx'
import Chat from './pages/Chat.jsx'
import Gallery from './pages/Gallery.jsx'

function Shell() {
  const { t, lang, setLang } = useStrings()
  const [user, setUser] = useState(null)
  const [view, setView] = useState('chat')
  // Counts taps on "chat": one while the chat already shows still closes the phone's list over it.
  const [chatTaps, setChatTaps] = useState(0)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    if (!getToken()) { setChecking(false); return }
    api.me().then(setUser).catch(() => setToken(null)).finally(() => setChecking(false))
  }, [])

  function signOut() {
    setToken(null)
    setUser(null)
  }

  if (checking) return <div className="p-6 text-sm text-slate-500">{t.loading}</div>
  if (!user) return <Login onSignedIn={setUser} />

  return (
    <div className="flex flex-col h-full">
      <nav className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-white px-4 py-2 text-sm sm:gap-x-4">
        <span className="hidden font-semibold sm:inline">{t.appName}</span>
        {['chat', 'gallery'].map((v) => (
          <button key={v} onClick={() => { setView(v); if (v === 'chat') setChatTaps((n) => n + 1) }}
            className={view === v ? 'font-medium underline' : 'text-slate-500'}>
            {t[v]}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-x-3 sm:gap-x-4">
          <span className="text-slate-500">
            <span className="hidden sm:inline">{user.email} · </span>{t.left(user.quota_remaining)}
          </span>
          <button data-testid="language-switch" type="button"
            onClick={() => setLang(lang === 'vi' ? 'en' : 'vi')}
            className="rounded border px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100">
            {t.language}
          </button>
          <button onClick={signOut} className="text-slate-500 hover:underline">{t.signOut}</button>
        </div>
      </nav>
      <main className="flex-1 min-h-0">
        {view === 'chat'
          ? <Chat chatTaps={chatTaps} onQuotaSpent={() => api.me().then(setUser).catch(() => {})} />
          : <Gallery />}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <LanguageProvider>
      <Shell />
    </LanguageProvider>
  )
}
