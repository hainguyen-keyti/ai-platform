import { useEffect, useRef, useState } from 'react'
import { api, waitForJob } from '../lib/api.js'
import MediaImage from '../components/MediaImage.jsx'
import TypingBubble from '../components/TypingBubble.jsx'
import Lightbox from '../components/Lightbox.jsx'

const PROVIDERS = ['chatgpt', 'grok', 'gemini']
const SLOW_HINT = 'Still working. Asking for a picture takes the longest.'
const STICK_THRESHOLD_PX = 80

export default function Chat({ onQuotaSpent }) {
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [conversation, setConversation] = useState(null)
  const [provider, setProvider] = useState('chatgpt')
  const [input, setInput] = useState('')
  const [status, setStatus] = useState(null)
  const [pendingHint, setPendingHint] = useState(null)
  const [error, setError] = useState(null)
  const [viewing, setViewing] = useState(null)

  function open(url, item) {
    setViewing({ url, filename: item.filename })
  }

  const scrollRef = useRef(null)
  // Following the tail is the default, but someone who scrolled up to reread
  // history must not be yanked back down when a reply lands.
  const stickToBottom = useRef(true)

  useEffect(() => { refreshList() }, [])
  useEffect(() => {
    stickToBottom.current = true
    if (!activeId) { setConversation(null); return }
    api.conversation(activeId).then(setConversation).catch((e) => setError(e.message))
  }, [activeId])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !stickToBottom.current) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [conversation, status])

  function trackScroll() {
    const el = scrollRef.current
    if (!el) return
    stickToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX
  }

  async function refreshList() {
    try {
      const data = await api.conversations()
      setConversations(data.items)
    } catch (err) {
      setError(err.message)
    }
  }

  async function runJob(starter, hint = null) {
    setError(null)
    setStatus('queued')
    setPendingHint(hint)
    // Sending is an explicit request to watch the tail again.
    stickToBottom.current = true
    try {
      const created = await starter()
      setActiveId(created.conversation_id)
      await waitForJob(created.job_id, setStatus)
      const fresh = await api.conversation(created.conversation_id)
      setConversation(fresh)
      refreshList()
      // Every job costs a credit, so the number in the nav is stale the moment
      // one finishes.
      if (onQuotaSpent) onQuotaSpent()
    } catch (err) {
      setError(err.message)
    } finally {
      setStatus(null)
      setPendingHint(null)
    }
  }

  function send(event) {
    event.preventDefault()
    const text = input.trim()
    if (!text || status) return
    setInput('')
    // One way in. The provider returns whatever the reply turned out to be, so
    // asking the user to declare "this one is a picture" bought nothing.
    runJob(() => api.chat({ provider, conversation_id: activeId, message: text }), SLOW_HINT)
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
          {error && <span className="text-sm text-red-600">{error}</span>}
        </header>

        <div ref={scrollRef} onScroll={trackScroll} data-testid="message-scroll"
          className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50">
          {!conversation && <p className="text-slate-400 text-sm">Start a new conversation.</p>}

          {conversation?.messages.map((m) => (
            <div key={m.id} className={`flex flex-col gap-2 ${
              m.role === 'user' ? 'items-end' : 'items-start'}`}>
              {m.content && (
                <div className={`max-w-2xl whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                  m.role === 'user' ? 'bg-slate-900 text-white' : 'bg-white border'}`}>
                  {m.content}
                </div>
              )}
              {m.media?.map((item) => (
                <div key={item.id} className="w-64 rounded border bg-white p-2">
                  <MediaImage id={item.id} className="w-full" onOpen={(url) => open(url, item)} />
                  <button onClick={() => requestScript(item.id)} disabled={!!status}
                    className="mt-2 w-full rounded border py-1 text-xs hover:bg-slate-100 disabled:opacity-50">
                    Video script
                  </button>
                </div>
              ))}
            </div>
          ))}

          {conversation?.orphan_media?.length > 0 && (
            <div className="grid grid-cols-2 gap-3 pt-2 md:grid-cols-3">
              {conversation.orphan_media.map((item) => (
                <div key={item.id} className="space-y-2 rounded border bg-white p-2">
                  <MediaImage id={item.id} className="w-full" onOpen={(url) => open(url, item)} />
                  <button onClick={() => requestScript(item.id)} disabled={!!status}
                    className="w-full rounded border py-1 text-xs hover:bg-slate-100 disabled:opacity-50">
                    Video script
                  </button>
                </div>
              ))}
            </div>
          )}

          {status && <TypingBubble hint={pendingHint} />}
        </div>

        <Lightbox url={viewing?.url} filename={viewing?.filename}
          onClose={() => setViewing(null)} />

        <form onSubmit={send} className="flex gap-2 border-t bg-white p-3">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message, or ask for a picture..."
            className="flex-1 border rounded px-3 py-2 text-sm" />
          <button disabled={!!status} className="bg-slate-900 text-white rounded px-4 text-sm disabled:opacity-50">
            Send
          </button>
        </form>
      </section>
    </div>
  )
}
