import { useEffect, useMemo, useRef, useState } from 'react'
import { api, conversationZipUrl, waitForJob } from '../lib/api.js'
import MediaImage from '../components/MediaImage.jsx'
import TypingBubble from '../components/TypingBubble.jsx'
import Lightbox from '../components/Lightbox.jsx'
import FileCard from '../components/FileCard.jsx'

const PROVIDERS = ['chatgpt', 'grok', 'gemini']
const SLOW_HINT = 'Still working. Asking for a picture takes the longest.'
const STICK_THRESHOLD_PX = 80

function MediaCard({ item, busy, onOpen, onScript }) {
  // Whatever came back is shown as what it is. Only a picture can be previewed
  // or turned into a video script.
  if (item.type !== 'image') return <FileCard item={item} />

  return (
    <div className="w-64 rounded border bg-white p-2">
      <MediaImage id={item.id} className="w-full" onOpen={(url) => onOpen(url, item)} />
      <button onClick={() => onScript(item.id)} disabled={busy}
        className="mt-2 w-full rounded border py-1 text-xs hover:bg-slate-100 disabled:opacity-50">
        Video script
      </button>
    </div>
  )
}

export default function Chat({ onQuotaSpent }) {
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [conversation, setConversation] = useState(null)
  const [provider, setProvider] = useState('chatgpt')
  const [input, setInput] = useState('')
  const [status, setStatus] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [phase, setPhase] = useState(null)
  const [pendingHint, setPendingHint] = useState(null)
  const [error, setError] = useState(null)
  const [viewing, setViewing] = useState(null)
  const [packing, setPacking] = useState(false)

  function open(url, item) {
    setViewing({ url, filename: item.filename })
  }

  // Everything the conversation produced, or one message's worth, in one zip
  // built by the api from bytes it already holds. Asking the model to package
  // its own output worked in one of four measured attempts.
  async function saveZip(messageId) {
    if (!conversation || packing) return
    setPacking(true)
    setError(null)
    try {
      const { url, filename } = await conversationZipUrl(conversation.id, messageId)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      // Revoking straight away can cancel the transfer that just started.
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (err) {
      setError(err.message)
    } finally {
      setPacking(false)
    }
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

  // Media from before media carried a message id has no bubble to sit under.
  // Pinning it after the messages put old pictures below newer replies, so it
  // is merged into the same list and ordered by time like everything else.
  const timeline = useMemo(() => {
    if (!conversation) return []
    const items = conversation.messages.map((m) => ({ kind: 'message', at: m.created_at, id: m.id, message: m }))
    for (const item of conversation.orphan_media || []) {
      items.push({ kind: 'media', at: item.created_at, id: item.id, media: item })
    }
    return items.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))
  }, [conversation])

  const mediaCount = useMemo(() => {
    if (!conversation) return 0
    return conversation.messages.reduce((n, m) => n + (m.media?.length || 0), 0)
      + (conversation.orphan_media?.length || 0)
  }, [conversation])

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
      // Show what was just said straight away. Setting the id alone does not
      // reload an already open conversation, so a follow-up message stayed
      // invisible until its job finished, which for a picture is minutes.
      setConversation(await api.conversation(created.conversation_id))
      setJobId(created.job_id)
      await waitForJob(created.job_id, (s, p) => { setStatus(s); setPhase(p) })
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
      setJobId(null)
      setPhase(null)
      setPendingHint(null)
    }
  }

  async function stopJob() {
    if (!jobId) return
    try {
      // The api settles it at once and gives the credit back; the poll in
      // runJob sees "cancelled" and unwinds on its own.
      await api.cancelJob(jobId)
    } catch (err) {
      setError(err.message)
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
          {mediaCount >= 2 && (
            <button type="button" data-testid="download-all" onClick={() => saveZip()}
              disabled={packing}
              className="rounded border px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50">
              {packing ? 'Packing...' : `Download all (${mediaCount})`}
            </button>
          )}
          {error && <span className="text-sm text-red-600">{error}</span>}
        </header>

        <div ref={scrollRef} onScroll={trackScroll} data-testid="message-scroll"
          className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50">
          {!conversation && <p className="text-slate-400 text-sm">Start a new conversation.</p>}

          {timeline.map((entry) =>
            entry.kind === 'media' ? (
              <div key={entry.id} className="flex flex-col items-start gap-2">
                <MediaCard item={entry.media} busy={!!status}
                  onOpen={open} onScript={requestScript} />
              </div>
            ) : (
              <div key={entry.id} className={`flex flex-col gap-2 ${
                entry.message.role === 'user' ? 'items-end' : 'items-start'}`}>
                {entry.message.content && (
                  <div className={`max-w-2xl whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                    entry.message.role === 'user' ? 'bg-slate-900 text-white' : 'bg-white border'}`}>
                    {entry.message.content}
                  </div>
                )}
                {entry.message.media?.map((item) => (
                  <MediaCard key={item.id} item={item} busy={!!status}
                    onOpen={open} onScript={requestScript} />
                ))}
                {(entry.message.media?.length || 0) >= 2 && (
                  <button type="button" data-testid="download-message" disabled={packing}
                    onClick={() => saveZip(entry.message.id)}
                    className="text-xs text-slate-500 underline hover:text-slate-900 disabled:opacity-50">
                    Download these {entry.message.media.length} as one zip
                  </button>
                )}
              </div>
            )
          )}

          {status && <TypingBubble hint={pendingHint} phase={phase} />}
        </div>

        <Lightbox url={viewing?.url} filename={viewing?.filename}
          onClose={() => setViewing(null)} />

        <form onSubmit={send} className="flex gap-2 border-t bg-white p-3">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message, or ask for a picture..."
            className="flex-1 border rounded px-3 py-2 text-sm" />
          {status ? (
            <button type="button" onClick={stopJob}
              className="rounded bg-red-600 px-4 text-sm text-white hover:bg-red-700">
              Stop
            </button>
          ) : (
            <button type="submit" className="bg-slate-900 text-white rounded px-4 text-sm">
              Send
            </button>
          )}
        </form>
      </section>
    </div>
  )
}
