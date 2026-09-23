import { useEffect, useState } from 'react'
import { mediaBlobUrl } from '../lib/api.js'

export default function MediaImage({ id, className = '', alt = 'generated image' }) {
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
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [id])

  if (error) return <div className="text-xs text-red-600">{error}</div>
  if (!url) return <div className={`animate-pulse bg-slate-200 rounded ${className}`} />
  return <img src={url} alt={alt} className={`rounded ${className}`} />
}
