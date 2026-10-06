import { useEffect, useState } from 'react'
import { mediaBlobUrl } from '../lib/api.js'
import { useStrings } from '../lib/strings.jsx'

export default function MediaVideo({ item, className = '' }) {
  const { t } = useStrings()
  const [url, setUrl] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let revoked = null
    let cancelled = false
    mediaBlobUrl(item.id)
      .then((objectUrl) => {
        if (cancelled) {
          URL.revokeObjectURL(objectUrl)
          return
        }
        revoked = objectUrl
        setUrl(objectUrl)
      })
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [item.id])

  return (
    <div className={className}>
      {error ? (
        <p className="text-xs text-red-600">{error}</p>
      ) : url ? (
        <>
          <video src={url} controls playsInline preload="metadata" data-testid="media-video"
            className="w-full rounded bg-black" />
          <a href={url} download={item.metadata?.name || item.filename} data-testid="video-download"
            className="mt-2 block w-full rounded border py-1 text-center text-xs hover:bg-slate-100">
            {t.download}
          </a>
        </>
      ) : (
        <div className="aspect-video w-full animate-pulse rounded bg-slate-200" />
      )}
    </div>
  )
}
