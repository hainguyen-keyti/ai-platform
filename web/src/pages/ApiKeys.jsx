import { useEffect, useState } from 'react'
import { api, apiBase } from '../lib/api.js'
import { useStrings } from '../lib/strings.jsx'

// The api stores UTC without a zone; read it as UTC so the date is the person's own.
function day(stamp, lang) {
  return new Date(stamp.replace(' ', 'T') + 'Z').toLocaleDateString(lang === 'vi' ? 'vi-VN' : 'en-GB')
}

export default function ApiKeys() {
  const { t, lang } = useStrings()
  const [keys, setKeys] = useState(null)
  const [name, setName] = useState('')
  const [made, setMade] = useState(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { load() }, [])

  async function load() {
    try {
      setKeys((await api.apiKeys()).items)
    } catch (err) {
      setError(err.message)
    }
  }

  async function create(event) {
    event.preventDefault()
    if (!name.trim() || busy) return
    setBusy(true)
    setError(null)
    setCopied(false)
    try {
      setMade(await api.createApiKey(name.trim()))
      setName('')
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function revoke(item) {
    if (!window.confirm(t.confirmRevoke(item.name))) return
    try {
      await api.revokeApiKey(item.id)
      if (made?.id === item.id) setMade(null)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(made.key)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  const example = [
    `curl -X POST ${apiBase}/v1/images \\`,
    '  -H "Authorization: Bearer YOUR_KEY" \\',
    '  -F "prompt=a red fox in the snow" \\',
    '  -F "image=@photo.png"',
    '',
    `curl -H "Authorization: Bearer YOUR_KEY" ${apiBase}/v1/images/REQUEST_ID`,
  ].join('\n')

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-4 sm:p-6">
      <div className="mx-auto max-w-2xl space-y-6">
        <section>
          <h2 className="text-lg font-semibold">{t.apiKeysTitle}</h2>
          <p className="mt-1 text-sm text-slate-600">{t.apiKeysIntro}</p>
        </section>

        {error && <p className="text-sm text-red-700">{error}</p>}

        <form onSubmit={create} className="flex flex-col gap-2 sm:flex-row">
          <input data-testid="key-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={60}
            aria-label={t.keyName} placeholder={t.keyNamePlaceholder}
            className="h-10 min-w-0 flex-1 rounded border bg-white px-3 text-base placeholder:text-slate-500 md:text-sm" />
          <button data-testid="key-create" type="submit" disabled={!name.trim() || busy}
            className="h-10 rounded bg-slate-900 px-4 text-sm text-white disabled:opacity-50">
            {t.createKey}
          </button>
        </form>

        {made && (
          <div role="status" className="space-y-2 rounded border border-amber-300 bg-amber-50 p-3">
            <p className="text-sm font-medium text-amber-900">{t.keyShownOnce}</p>
            <code data-testid="new-key"
              className="block break-all rounded bg-white px-2 py-1 font-mono text-sm text-slate-900">
              {made.key}
            </code>
            <button type="button" data-testid="copy-key" onClick={copy}
              className="h-9 rounded border border-amber-300 bg-white px-3 text-sm text-slate-900 hover:bg-amber-100">
              {copied ? t.copied : t.copy}
            </button>
          </div>
        )}

        <section>
          <h3 className="mb-2 text-sm font-semibold">{t.yourKeys}</h3>
          {keys && keys.length === 0 && <p className="text-sm text-slate-600">{t.noKeys}</p>}
          {keys && keys.length > 0 && (
            <ul className="divide-y rounded border bg-white">
              {keys.map((item) => (
                <li key={item.id} data-testid="key-row" className="flex items-center justify-between gap-3 px-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{item.name}</p>
                    <p className="text-xs text-slate-600">
                      <span className="font-mono">{item.prefix}…</span>
                      {' · '}{t.keyCreated(day(item.created_at, lang))}
                      {' · '}{item.last_used_at ? t.keyUsed(day(item.last_used_at, lang)) : t.keyNeverUsed}
                    </p>
                  </div>
                  <button type="button" data-testid="key-revoke" onClick={() => revoke(item)}
                    className="h-9 shrink-0 px-2 text-sm text-red-700 hover:underline">
                    {t.revoke}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold">{t.howToCall}</h3>
          <pre className="overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{example}</pre>
          <p className="mt-2 text-xs text-slate-600">{t.howToCallNote}</p>
        </section>
      </div>
    </div>
  )
}
