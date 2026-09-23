import { useEffect } from 'react'

export default function Lightbox({ url, filename, onClose }) {
  useEffect(() => {
    function onKey(event) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!url) return null

  return (
    <div data-testid="lightbox" onClick={onClose}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-black/80 p-6">
      <img src={url} alt={filename || 'media'}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[80vh] max-w-full rounded object-contain" />
      <div className="flex gap-3" onClick={(e) => e.stopPropagation()}>
        <a data-testid="lightbox-download" href={url} download={filename || 'image.png'}
          className="rounded bg-white px-4 py-2 text-sm font-medium text-slate-900">
          Download
        </a>
        <button onClick={onClose} className="rounded bg-white/20 px-4 py-2 text-sm text-white">
          Close
        </button>
      </div>
    </div>
  )
}
