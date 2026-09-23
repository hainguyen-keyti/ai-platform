import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import MediaImage from '../components/MediaImage.jsx'

export default function Gallery() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(null)

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
      <h2 className="text-lg font-semibold mb-4">Gallery ({total})</h2>
      {error && <div className="text-sm text-red-600 mb-3">{error}</div>}
      {items.length === 0 && <p className="text-sm text-slate-400">Nothing generated yet.</p>}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {items.map((item) => (
          <div key={item.id} className="bg-white border rounded p-2 space-y-2">
            <MediaImage id={item.id} className="w-full" />
            <p className="text-xs text-slate-500 line-clamp-2">{item.prompt || item.filename}</p>
            <div className="flex justify-between text-xs text-slate-400">
              <span>{item.provider}</span>
              <button onClick={() => remove(item.id)} className="text-red-600 hover:underline">
                delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
