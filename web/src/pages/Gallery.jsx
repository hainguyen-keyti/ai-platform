import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { useStrings } from '../lib/strings.jsx'
import MediaImage from '../components/MediaImage.jsx'
import MediaVideo from '../components/MediaVideo.jsx'
import Lightbox from '../components/Lightbox.jsx'
import FileCard from '../components/FileCard.jsx'

export default function Gallery() {
  const { t } = useStrings()
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(null)
  const [viewing, setViewing] = useState(null)

  useEffect(() => { load() }, [])

  async function load() {
    try {
      const data = await api.media()
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      setError(err.message)
    }
  }

  async function remove(id) {
    try {
      await api.deleteMedia(id)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="p-6 overflow-y-auto h-full bg-slate-50">
      <h2 className="text-lg font-semibold mb-4">{t.galleryTitle(total)}</h2>
      {error && <div className="text-sm text-red-600 mb-3">{error}</div>}
      {items.length === 0 && <p className="text-sm text-slate-500">{t.nothingYet}</p>}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {items.map((item) => (
          <div key={item.id} className="bg-white border rounded p-2 space-y-2">
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

      <Lightbox url={viewing?.url} filename={viewing?.filename}
        onClose={() => setViewing(null)} />
    </div>
  )
}
