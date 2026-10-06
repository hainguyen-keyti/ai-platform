import { useEffect, useState } from 'react'
import { mediaBlobUrl } from '../lib/api.js'
import { useStrings } from '../lib/strings.jsx'

export default function MediaVideo({ item, className = '' }) {
  const { t } = useStrings()
  const [url, setUrl] = useState(null)
  const [failed, setFailed] = useState(false)

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
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [item.id])

  if (failed) {
    return (
      <div className={className}>
        <p data-testid="video-failed"
          className="flex aspect-video w-full items-center justify-center rounded bg-slate-100 p-2 text-center text-xs text-red-700">
          {t.videoFailed}
        </p>
      </div>
    )
  }

  // While loading, the player's box and its Download row hold their place, so the card does not jump.
  return (
    <div className={className}>
      {url ? (
        <video src={url} controls playsInline preload="metadata" data-testid="media-video"
          aria-label={t.videoLabel} className="max-h-[60vh] w-full rounded bg-black object-contain" />
      ) : (
        <div className="aspect-video w-full animate-pulse rounded bg-slate-200" />
      )}
      {url ? (
        <a href={url} download={item.metadata?.name || item.filename} data-testid="video-download"
          className="mt-2 block w-full rounded border py-1 text-center text-xs hover:bg-slate-100">
          {t.download}
        </a>
      ) : (
        <div className="mt-2 h-[26px] w-full rounded border bg-slate-50" />
      )}
    </div>
  )
}
