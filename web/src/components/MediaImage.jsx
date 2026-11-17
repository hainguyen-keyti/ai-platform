import { useEffect, useState } from 'react'
import { mediaBlobUrl } from '../lib/api.js'
import { failureText, useStrings } from '../lib/strings.jsx'

export default function MediaImage({ id, className = '', alt = 'generated image', onOpen }) {
  const { t } = useStrings()
  const [url, setUrl] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let revoked = null
    let cancelled = false
    mediaBlobUrl(id)
      .then((objectUrl) => {
        if (cancelled) {
          URL.revokeObjectURL(objectUrl)
          return
        }
        revoked = objectUrl
        setUrl(objectUrl)
      })
      .catch((err) => !cancelled && setError(err))
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [id])

  if (error) {
    return <div data-testid="image-failed" className="text-xs text-red-600" title={error.message}>{failureText(error, t)}</div>
  }
  if (!url) return <div className={`animate-pulse bg-slate-200 rounded ${className}`} />

  return (
    <img
      src={url}
      alt={alt}
      data-testid="media-thumb"
      onClick={onOpen ? () => onOpen(url) : undefined}
      className={`rounded ${onOpen ? 'cursor-zoom-in' : ''} ${className}`}
    />
  )
}
