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
  // Null until the list has answered once: a gallery that could not load is not an empty one.
  const [total, setTotal] = useState(null)
  // A page that brought nothing new: something arrived at the top meanwhile, so asking on would repeat.
  const [atEnd, setAtEnd] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)
  // Where the failure is shown: beside "show more" when that is what failed, at the top otherwise.
  const [errorAtMore, setErrorAtMore] = useState(false)
  const [viewing, setViewing] = useState(null)

  useEffect(() => { load(0) }, [])

  async function load(offset) {
    setError(null)
    try {
      const data = await api.media(offset)
      const known = new Set(items.map((i) => i.id))
      // Merged into the list as it is now, so a tile deleted while the page loaded stays gone.
      setItems((shown) => {
        const before = offset ? shown : []
        const seen = new Set(before.map((i) => i.id))
        return [...before, ...data.items.filter((i) => !seen.has(i.id))]
      })
      setAtEnd(data.items.length < MEDIA_PAGE || (offset > 0 && data.items.every((i) => known.has(i.id))))
      setTotal(data.total)
    } catch (err) {
      setErrorAtMore(offset > 0)
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
    setError(null)
    try {
      await api.deleteMedia(id)
      // Taken out where it stands: the pages already shown stay, and the next one starts right.
      setItems((shown) => shown.filter((i) => i.id !== id))
      setTotal((n) => n - 1)
    } catch (err) {
      setErrorAtMore(false)
      setError(err)
    }
  }

  const failure = error && (
    <div className="mb-3 text-sm text-red-600" title={error.message}>{failureText(error, t)}</div>
  )

  return (
    <div className="p-6 overflow-y-auto h-full bg-slate-50">
      <h2 className="text-lg font-semibold mb-4">{total === null ? t.galleryHeading : t.galleryTitle(total)}</h2>
      {!errorAtMore && failure}
      {total === null && error && (
        <button type="button" data-testid="gallery-retry" onClick={() => load(0)}
          className="mb-3 h-10 rounded border bg-white px-4 text-sm hover:bg-slate-100">
          {t.retry}
        </button>
      )}
      {total === 0 && <p className="text-sm text-slate-500">{t.nothingYet}</p>}

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

      {errorAtMore && <div className="mt-4">{failure}</div>}
      {!atEnd && total !== null && items.length < total && (
        <button type="button" data-testid="gallery-more" onClick={showMore} disabled={loadingMore}
          className="mt-4 h-10 rounded border bg-white px-4 text-sm hover:bg-slate-100 disabled:opacity-50">
          {loadingMore ? t.loading : t.showMore(total - items.length)}
        </button>
      )}

      <Lightbox url={viewing?.url} filename={viewing?.filename}
        onClose={() => setViewing(null)} />
    </div>
  )
}
