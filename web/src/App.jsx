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
      <nav className="flex items-center gap-4 border-b bg-white px-4 py-2 text-sm">
        <span className="font-semibold">{t.appName}</span>
        {['chat', 'gallery'].map((v) => (
          <button key={v} onClick={() => setView(v)}
            className={view === v ? 'font-medium underline' : 'text-slate-500'}>
            {t[v]}
          </button>
        ))}
        <span className="ml-auto text-slate-500">
          {user.email} · {user.quota_remaining} {t.left}
        </span>
        <button data-testid="language-switch" type="button"
          onClick={() => setLang(lang === 'vi' ? 'en' : 'vi')}
          className="rounded border px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100">
          {t.language}
        </button>
        <button onClick={signOut} className="text-slate-500 hover:underline">{t.signOut}</button>
      </nav>
      <main className="flex-1 min-h-0">
        {view === 'chat'
          ? <Chat onQuotaSpent={() => api.me().then(setUser).catch(() => {})} />
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
