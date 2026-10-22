import { useEffect, useRef, useState } from 'react'
import { api, getToken, setToken, whenUnauthorized } from './lib/api.js'
import { failureText, LanguageProvider, useStrings } from './lib/strings.jsx'
import Login from './pages/Login.jsx'
import Chat from './pages/Chat.jsx'
import Gallery from './pages/Gallery.jsx'
import ApiKeys from './pages/ApiKeys.jsx'

function Shell() {
  const { t, lang, setLang } = useStrings()
  const [user, setUser] = useState(null)
  const [view, setView] = useState('chat')
  // Counts taps on "chat": one while the chat already shows still closes the phone's list over it.
  const [chatTaps, setChatTaps] = useState(0)
  const [checking, setChecking] = useState(true)
  // The first look at the account failed for a reason other than the login: the session is kept.
  const [unreachable, setUnreachable] = useState(null)
  // Only the latest look counts (the dev build looks twice, a retry looks again).
  const looks = useRef(0)

  useEffect(() => {
    whenUnauthorized(() => setUser(null))
    return () => whenUnauthorized(null)
  }, [])

  function lookAtAccount() {
    const look = ++looks.current
    if (!getToken()) { setChecking(false); return }
    setChecking(true)
    setUnreachable(null)
    api.me()
      .then((me) => { if (look === looks.current) setUser(me) })
      .catch((err) => { if (look === looks.current && err.status !== 401) setUnreachable(err) })
      .finally(() => { if (look === looks.current) setChecking(false) })
  }

  useEffect(() => { lookAtAccount() }, [])

  function signOut() {
    // Ended on the server too; the call already carries the token, so the session is forgotten
    // here at once, and a server that cannot be reached does not hold the person up.
    api.logout().catch(() => {})
    setToken(null)
    setUser(null)
  }

  if (checking) return <div className="p-6 text-sm text-slate-500">{t.loading}</div>
  if (unreachable) {
    return (
      <div className="p-6 text-sm">
        <p className="text-slate-700" title={unreachable.message}>{failureText(unreachable, t)}</p>
        <button type="button" data-testid="retry-connection" onClick={lookAtAccount}
          className="mt-3 h-10 rounded border px-4 hover:bg-slate-100">
          {t.retry}
        </button>
      </div>
    )
  }
  if (!user) return <Login onSignedIn={setUser} />

  return (
    <div className="flex flex-col h-full">
      <nav className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b bg-white px-2 py-2 text-sm sm:gap-x-4 sm:px-4">
        <span className="hidden font-semibold sm:inline">{t.appName}</span>
        {['chat', 'gallery', 'api'].map((v) => (
          <button key={v} onClick={() => { setView(v); if (v === 'chat') setChatTaps((n) => n + 1) }}
            className={view === v ? 'font-medium underline' : 'text-slate-500'}>
            {t[v]}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-x-2 sm:gap-x-4">
          <span className="text-slate-500">
            <span className="hidden max-w-[16rem] truncate align-bottom sm:inline-block">{user.email}</span>
            <span className="hidden sm:inline"> · </span>{t.left(user.quota_remaining)}
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
        {/* Kept mounted while another view shows: a running job keeps its poll, its Stop and its reply. */}
        <div className={view === 'chat' ? 'h-full' : 'hidden'}>
          <Chat chatTaps={chatTaps} visible={view === 'chat'}
            onQuotaSpent={() => api.me().then(setUser).catch(() => {})} />
        </div>
        {view === 'gallery' && <Gallery />}
        {view === 'api' && <ApiKeys />}
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
