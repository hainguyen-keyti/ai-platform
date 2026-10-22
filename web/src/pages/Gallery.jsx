import { useEffect, useState } from 'react'
import { api, MEDIA_PAGE } from '../lib/api.js'
import { failureText, useStrings } from '../lib/strings.jsx'
import MediaImage from '../components/MediaImage.jsx'
import MediaVideo from '../components/MediaVideo.jsx'
import Lightbox from '../components/Lightbox.jsx'
import FileCard from '../components/FileCard.jsx'

export default function Gallery() {
  const { t } = useStrings()
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  // A page that brought nothing new: something arrived at the top meanwhile, so asking on would repeat.
  const [atEnd, setAtEnd] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)
  const [viewing, setViewing] = useState(null)

  useEffect(() => { load(0) }, [])

  async function load(offset) {
    try {
      const data = await api.media(offset)
      const before = offset ? items : []
      const seen = new Set(before.map((i) => i.id))
      const fresh = data.items.filter((i) => !seen.has(i.id))
      setItems([...before, ...fresh])
      setAtEnd(fresh.length === 0 || data.items.length < MEDIA_PAGE)
      setTotal(data.total)
    } catch (err) {
      setError(err)
    }
  }

  async function showMore() {
    setLoadingMore(true)
    await load(items.length)
    setLoadingMore(false)
  }

  async function remove(id) {
    if (!window.confirm(t.confirmDeleteMedia)) return
    try {
      await api.deleteMedia(id)
      // Taken out where it stands: the pages already shown stay, and the next one starts right.
      setItems((shown) => shown.filter((i) => i.id !== id))
      setTotal((n) => n - 1)
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="p-6 overflow-y-auto h-full bg-slate-50">
      <h2 className="text-lg font-semibold mb-4">{t.galleryTitle(total)}</h2>
      {error && <div className="text-sm text-red-600 mb-3" title={error.message}>{failureText(error, t)}</div>}
      {items.length === 0 && <p className="text-sm text-slate-500">{t.nothingYet}</p>}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {items.map((item) => (
          <div key={item.id}
            className={`bg-white border rounded p-2 space-y-2 ${item.type === 'video' ? 'col-span-2 md:col-span-1' : ''}`}>
            {item.type === 'image' ? (
              <MediaImage id={item.id} className="w-full"
                onOpen={(url) => setViewing({ url, filename: item.filename })} />
            ) : item.type === 'video' ? (
              <MediaVideo item={item} />
            ) : (
              <FileCard item={item} />
            )}
            <p className="text-xs text-slate-500 line-clamp-2">{item.prompt || item.filename}</p>
            <div className="flex justify-between text-xs text-slate-500">
              <span>{item.provider}</span>
              <button onClick={() => remove(item.id)} className="text-red-600 hover:underline">
                {t.delete.toLowerCase()}
              </button>
            </div>
          </div>
        ))}
      </div>

      {!atEnd && items.length < total && (
        <button type="button" data-testid="gallery-more" onClick={showMore} disabled={loadingMore}
          className="mt-4 rounded border bg-white px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50">
          {loadingMore ? t.loading : t.showMore(total - items.length)}
        </button>
      )}

      <Lightbox url={viewing?.url} filename={viewing?.filename}
        onClose={() => setViewing(null)} />
    </div>
  )
}
