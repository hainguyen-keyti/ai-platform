import { useEffect, useState } from 'react'
import { api, waitForJob } from '../lib/api.js'
import MediaImage from '../components/MediaImage.jsx'

const PROVIDERS = ['chatgpt', 'grok', 'gemini']

export default function Chat() {
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [conversation, setConversation] = useState(null)
  const [provider, setProvider] = useState('chatgpt')
  const [mode, setMode] = useState('chat')
  const [input, setInput] = useState('')
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { refreshList() }, [])
  useEffect(() => {
    if (!activeId) { setConversation(null); return }
    api.conversation(activeId).then(setConversation).catch((e) => setError(e.message))
  }, [activeId])

  async function refreshList() {
    try {
      const data = await api.conversations()
      setConversations(data.items)
    } catch (err) {
      setError(err.message)
    }
  }

  async function runJob(starter) {
    setError(null)
    setStatus('queued')
    try {
      const created = await starter()
      setActiveId(created.conversation_id)
      await waitForJob(created.job_id, setStatus)
      const fresh = await api.conversation(created.conversation_id)
      setConversation(fresh)
      refreshList()
    } catch (err) {
      setError(err.message)
    } finally {
      setStatus(null)
    }
  }

  function send(event) {
    event.preventDefault()
    const text = input.trim()
    if (!text || status) return
    setInput('')
    const payload = { provider, conversation_id: activeId }
    runJob(() =>
      mode === 'image'
        ? api.image({ ...payload, prompt: text })
        : api.chat({ ...payload, message: text })
    )
  }

  function requestScript(mediaId) {
    if (status) return
    runJob(() => api.videoScript({ provider, media_id: mediaId, conversation_id: activeId }))
  }

  return (
    <div className="flex h-full">
      <aside className="w-64 border-r bg-white flex flex-col">
        <button onClick={() => { setActiveId(null); setConversation(null) }}
          className="m-3 rounded bg-slate-900 text-white py-2 text-sm">
          New chat
        </button>
        <div className="flex-1 overflow-y-auto">
          {conversations.map((c) => (
            <button key={c.id} onClick={() => setActiveId(c.id)}
              className={`block w-full text-left px-3 py-2 text-sm truncate hover:bg-slate-100 ${
                c.id === activeId ? 'bg-slate-100 font-medium' : ''}`}>
              <span className="text-slate-400 mr-1">{c.provider}</span>
              {c.title || 'Untitled'}
            </button>
          ))}
        </div>
      </aside>

      <section className="flex-1 flex flex-col">
        <header className="flex items-center gap-3 border-b bg-white px-4 py-2">
          <select value={provider} onChange={(e) => setProvider(e.target.value)}
            className="border rounded px-2 py-1 text-sm">
            {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <div className="flex text-sm rounded overflow-hidden border">
            {['chat', 'image'].map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={`px-3 py-1 ${mode === m ? 'bg-slate-900 text-white' : 'bg-white'}`}>
                {m}
              </button>
            ))}
          </div>
          {status && <span className="text-sm text-amber-600">job {status}...</span>}
          {error && <span className="text-sm text-red-600">{error}</span>}
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50">
          {!conversation && <p className="text-slate-400 text-sm">Start a new conversation.</p>}

          {conversation?.messages.map((m) => (
            <div key={m.id} className={m.role === 'user' ? 'text-right' : ''}>
              <div className={`inline-block max-w-2xl whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                m.role === 'user' ? 'bg-slate-900 text-white' : 'bg-white border'}`}>
                {m.content}
              </div>
            </div>
          ))}

          {conversation?.media?.length > 0 && (
            <div className="grid grid-cols-2 gap-3 pt-2 md:grid-cols-3">
              {conversation.media.map((item) => (
                <div key={item.id} className="bg-white border rounded p-2 space-y-2">
                  <MediaImage id={item.id} className="w-full" />
                  <button onClick={() => requestScript(item.id)} disabled={!!status}
                    className="w-full text-xs border rounded py-1 hover:bg-slate-100 disabled:opacity-50">
                    Video script
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <form onSubmit={send} className="flex gap-2 border-t bg-white p-3">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            placeholder={mode === 'image' ? 'Describe the image...' : 'Type a message...'}
            className="flex-1 border rounded px-3 py-2 text-sm" />
          <button disabled={!!status} className="bg-slate-900 text-white rounded px-4 text-sm disabled:opacity-50">
            Send
          </button>
        </form>
      </section>
    </div>
  )
}
