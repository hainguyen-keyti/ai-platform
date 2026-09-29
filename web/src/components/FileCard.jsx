import { useState } from 'react'
import { mediaBlobUrl } from '../lib/api.js'
import { useStrings } from '../lib/strings.jsx'

function readableSize(bytes) {
  if (!bytes) return null
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export default function FileCard({ item }) {
  const { t } = useStrings()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const name = item.metadata?.name || item.filename
  const size = readableSize(item.metadata?.size)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const url = await mediaBlobUrl(item.id)
      const link = document.createElement('a')
      link.href = url
      link.download = name
      link.click()
      // Revoking straight away can cancel the transfer that just started.
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-testid="file-card" className="w-full max-w-64 rounded border bg-white p-3">
      <div className="flex items-start gap-2">
        <span className="rounded bg-slate-100 px-2 py-1 text-[10px] font-medium uppercase text-slate-600">
          {(name.split('.').pop() || 'file').slice(0, 5)}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm" title={name}>{name}</p>
          {size && <p className="text-xs text-slate-500">{size}</p>}
        </div>
      </div>
      <button data-testid="file-download" onClick={save} disabled={busy}
        className="mt-2 w-full rounded border py-1 text-xs hover:bg-slate-100 disabled:opacity-50">
        {busy ? t.preparing : t.download}
      </button>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}
