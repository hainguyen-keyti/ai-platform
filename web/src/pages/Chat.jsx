import { useEffect, useMemo, useRef, useState } from 'react'
import Markdown, { defaultUrlTransform } from 'react-markdown'
import { api, conversationZipUrl, waitForJob } from '../lib/api.js'
import { useStrings } from '../lib/strings.jsx'
import MediaImage from '../components/MediaImage.jsx'
import TypingBubble from '../components/TypingBubble.jsx'
import Lightbox from '../components/Lightbox.jsx'
import FileCard from '../components/FileCard.jsx'

const PROVIDERS = ['chatgpt', 'grok', 'gemini']
const STICK_THRESHOLD_PX = 80
const BASE_TITLE = document.title

// A link the model writes to its own sandbox points nowhere a browser can go;
// the file itself is already a card under the text. Only link targets are let
// through so the component below can turn them into text; image sources and
// everything else keep react-markdown's own url rules.
function keepSandbox(url, key) {
  return key === 'href' && url.startsWith('sandbox:') ? url : defaultUrlTransform(url)
}

const markdownParts = {
  // An empty href is what react-markdown leaves of a javascript: or other
  // disallowed target; a link to nowhere is shown as plain text too.
  a: ({ href, children }) => (!href || href.startsWith('sandbox:')
    ? <span>{children}</span>
    : <a href={href} target="_blank" rel="noopener noreferrer" className="underline">{children}</a>),
}

function ReplyText({ text }) {
  return (
    <div data-testid="reply-bubble"
      className="max-w-[min(42rem,100%)] whitespace-pre-wrap rounded-lg border bg-white px-3 py-2 text-sm [overflow-wrap:anywhere] [&_p]:my-0 [&_ul]:my-1 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:my-1 [&_ol]:pl-5 [&_ol]:list-decimal [&_pre]:my-1 [&_pre]:overflow-x-auto [&_code]:text-xs">
      <Markdown urlTransform={keepSandbox} components={markdownParts}>{text}</Markdown>
    </div>
  )
}

function MediaCard({ item, busy, onOpen, onScript, label }) {
  // Whatever came back is shown as what it is. Only a picture can be previewed
  // or turned into a video script.
  if (item.type !== 'image') return <FileCard item={item} />

  return (
    <div className="w-64 rounded border bg-white p-2">
      <MediaImage id={item.id} className="w-full" onOpen={(url) => onOpen(url, item)} />
      <button onClick={() => onScript(item.id)} disabled={busy}
        className="mt-2 w-full rounded border py-1 text-xs hover:bg-slate-100 disabled:opacity-50">
        {label}
      </button>
    </div>
  )
}

export default function Chat({ onQuotaSpent }) {
  const { t } = useStrings()
  const [conversations, setConversations] = useState([])
  const [query, setQuery] = useState('')
  const [activeId, setActiveId] = useState(null)
  const [conversation, setConversation] = useState(null)
  const [provider, setProvider] = useState('chatgpt')
  const [input, setInput] = useState('')
  const [status, setStatus] = useState(null)
  const [phase, setPhase] = useState(null)
  // The job's id arrives one request after Send; Stop pressed before then is
  // remembered and honoured the moment the id is known.
  const jobRef = useRef(null)
  const cancelWanted = useRef(false)
  const [pendingHint, setPendingHint] = useState(null)
  const [error, setError] = useState(null)
  const [viewing, setViewing] = useState(null)
  const [packing, setPacking] = useState(false)
  const [renaming, setRenaming] = useState(null)
  const [draftTitle, setDraftTitle] = useState('')
  // On a phone the conversation list is a panel over the chat, opened on demand.
  const [listOpen, setListOpen] = useState(false)
  const openButton = useRef(null)
  const closeButton = useRef(null)
  // Which providers a worker serves right now, by name; until the api has answered, nothing is
  // held back (the api refuses a turn nobody serves anyway).
  const [served, setServed] = useState({})
  const unserved = served[provider] === false
  const anotherServed = PROVIDERS.some((p) => p !== provider && served[p] === true)
  // Only a provider nobody chose is ever moved on its own; a person's own choice is never swapped.
  const picked = useRef(false)
  const unseen = useRef(0)

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

  // The search box asks the api, which also looks inside messages; a short
  // pause so a person typing does not fire a request per keystroke.
  useEffect(() => {
    const id = setTimeout(() => { refreshList() }, 250)
    return () => clearTimeout(id)
  }, [query])

  useEffect(() => {
    stickToBottom.current = true
    if (!activeId) { setConversation(null); return }
    api.conversation(activeId).then(setConversation).catch((e) => setError(e.message))
  }, [activeId])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !stickToBottom.current) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [conversation, status, unserved])

  // A conversation holds one provider's thread, and the api refuses a turn from
  // another one. Follow the conversation rather than letting the two disagree.
  useEffect(() => {
    if (conversation?.provider) setProvider(conversation.provider)
  }, [conversation?.provider])

  useEffect(() => {
    let live = true
    async function ask() {
      try {
        const data = await api.providers()
        if (live) setServed(Object.fromEntries((data?.providers || []).map((p) => [p.name, p.served])))
      } catch { /* keep the last answer */ }
    }
    ask()
    const id = setInterval(ask, 60000)
    return () => { live = false; clearInterval(id) }
  }, [])

  // The open list takes the focus and gives it back to its button; Escape closes it.
  useEffect(() => {
    if (!listOpen) return
    closeButton.current?.focus()
    function onKey(event) {
      if (event.key === 'Escape') setListOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      openButton.current?.focus()
    }
  }, [listOpen])

  // The chat under the open list is inert, so a window widened past the phone layout closes the list.
  useEffect(() => {
    const wide = window.matchMedia('(min-width: 768px)')
    function close() {
      if (wide.matches) setListOpen(false)
    }
    wide.addEventListener('change', close)
    return () => wide.removeEventListener('change', close)
  }, [])

  // A new chat never starts on a provider nobody serves while another one is served.
  useEffect(() => {
    if (activeId || picked.current || served[provider] !== false) return
    const next = PROVIDERS.find((p) => served[p] === true)
    if (next) setProvider(next)
  }, [served, activeId, provider])

  // A reply that lands while the tab is hidden is counted in the title, and
  // announced when notifications were allowed; coming back clears it.
  useEffect(() => {
    function back() {
      if (!document.hidden) {
        unseen.current = 0
        document.title = BASE_TITLE
      }
    }
    document.addEventListener('visibilitychange', back)
    return () => document.removeEventListener('visibilitychange', back)
  }, [])

  function announce() {
    if (!document.hidden) return
    unseen.current += 1
    document.title = `(${unseen.current}) ${BASE_TITLE}`
    if ('Notification' in window && Notification.permission === 'granted') {
      try { new Notification(BASE_TITLE, { body: t.replyLanded }) } catch { /* not available here */ }
    }
  }

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
      const data = await api.conversations(query.trim())
      setConversations(data.items)
    } catch (err) {
      setError(err.message)
    }
  }

  async function runJob(starter, hint = null, draft = null) {
    setError(null)
    setStatus('queued')
    setPendingHint(hint)
    cancelWanted.current = false
    jobRef.current = null
    // Sending is an explicit request to watch the tail again.
    stickToBottom.current = true
    try {
      const created = await starter()
      jobRef.current = created.job_id
      if (cancelWanted.current) await api.cancelJob(created.job_id)
      setActiveId(created.conversation_id)
      // Show what was just said straight away. Setting the id alone does not
      // reload an already open conversation, so a follow-up message stayed
      // invisible until its job finished, which for a picture is minutes.
      setConversation(await api.conversation(created.conversation_id))
      await waitForJob(created.job_id, (s, p) => { setStatus(s); setPhase(p) })
      const fresh = await api.conversation(created.conversation_id)
      setConversation(fresh)
      announce()
      refreshList()
      // Every job costs a credit, so the number in the nav is stale the moment
      // one finishes.
      if (onQuotaSpent) onQuotaSpent()
    } catch (err) {
      // Refused before any job existed: nothing was sent, so the words go back in the box.
      if (!jobRef.current && draft) setInput(draft)
      // The api's word that nobody serves this provider beats the list asked a minute ago.
      if (err.status === 503) setServed((s) => ({ ...s, [provider]: false }))
      else setError(err.message)
    } finally {
      setStatus(null)
      jobRef.current = null
      setPhase(null)
      setPendingHint(null)
    }
  }

  async function stopJob() {
    cancelWanted.current = true
    if (!jobRef.current) return
    try {
      // The api settles it at once and gives the credit back; the poll in
      // runJob sees "cancelled" and unwinds on its own.
      await api.cancelJob(jobRef.current)
    } catch (err) {
      setError(err.message)
    }
  }

  function send(event) {
    event.preventDefault()
    const text = input.trim()
    if (!text || status || unserved) return
    setInput('')
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {})
    }
    // One way in. The provider returns whatever the reply turned out to be, so
    // asking the user to declare "this one is a picture" bought nothing.
    runJob(() => api.chat({ provider, conversation_id: activeId, message: text }), t.slowHint, text)
  }

  function requestScript(mediaId) {
    if (status || unserved) return
    runJob(() => api.videoScript({ provider, media_id: mediaId, conversation_id: activeId }))
  }

  function startRename(c) {
    setDraftTitle(c.title || '')
    setRenaming(c.id)
  }

  async function commitRename(id) {
    const title = draftTitle.trim()
    setRenaming(null)
    if (!title) return
    try {
      await api.renameConversation(id, title)
      if (conversation?.id === id) setConversation({ ...conversation, title })
      refreshList()
    } catch (err) {
      setError(err.message)
    }
  }

  async function removeConversation(id) {
    if (!window.confirm(t.confirmDelete)) return
    try {
      await api.deleteConversation(id)
      if (activeId === id) { setActiveId(null); setConversation(null) }
      refreshList()
    } catch (err) {
      setError(err.message)
    }
  }

  // Named from the list, so a phone's header reads right the moment a conversation is picked.
  const openTitle = activeId
    ? conversations.find((c) => c.id === activeId)?.title || (conversation?.id === activeId && conversation.title) || t.untitled
    : t.newChat

  return (
    <div className="relative flex h-full">
      <aside id="conversation-list"
        className={`${listOpen ? 'flex' : 'hidden'} absolute inset-0 z-20 w-full flex-col bg-white md:static md:z-auto md:flex md:w-64 md:border-r`}>
        <div className="flex items-center justify-between px-3 pt-3 md:hidden">
          <h2 className="text-base font-semibold">{t.conversations}</h2>
          <button type="button" ref={closeButton} data-testid="close-conversations"
            onClick={() => setListOpen(false)} className="rounded px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
            {t.close}
          </button>
        </div>
        <button onClick={() => { setActiveId(null); setConversation(null); setListOpen(false) }}
          className="m-3 rounded bg-slate-900 text-white py-2 text-sm">
          {t.newChat}
        </button>
        <input data-testid="conversation-search" value={query} placeholder={t.search}
          onChange={(e) => setQuery(e.target.value)}
          className="mx-3 mb-2 rounded border px-2 py-1 text-base md:text-sm" />
        {error && <p className="mx-3 mb-2 text-sm text-red-600 md:hidden">{error}</p>}
        <div className="flex-1 overflow-y-auto">
          {conversations.map((c) => (
            <div key={c.id} data-testid="conversation-item"
              className={`flex items-center gap-1 px-3 text-sm hover:bg-slate-100 ${
                c.id === activeId ? 'bg-slate-100 font-medium' : ''}`}>
              {renaming === c.id ? (
                <input data-testid="rename-input" autoFocus value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(c.id)
                    // Ends the rename only, not the list around it.
                    if (e.key === 'Escape') { e.stopPropagation(); setRenaming(null) }
                  }}
                  onBlur={() => setRenaming(null)}
                  className="min-w-0 flex-1 rounded border px-1 py-0.5 text-base font-normal md:text-sm" />
              ) : (
                <button onClick={() => { setActiveId(c.id); setListOpen(false) }}
                  className="min-w-0 flex-1 truncate py-3 text-left md:py-1.5">
                  <span className="text-slate-400 mr-1">{c.provider}</span>
                  {c.title || t.untitled}
                </button>
              )}
              <button data-testid="rename-conversation" type="button" title={t.rename} aria-label={t.rename}
                onClick={() => startRename(c)}
                className="px-3 py-3 text-slate-400 hover:text-slate-900 md:px-1 md:py-1.5">
                ✎
              </button>
              <button data-testid="delete-conversation" type="button" title={t.delete} aria-label={t.delete}
                onClick={() => removeConversation(c.id)}
                className="px-3 py-3 text-slate-400 hover:text-red-600 md:px-1 md:py-1.5">
                ×
              </button>
            </div>
          ))}
        </div>
      </aside>

      <section inert={listOpen ? '' : undefined} className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b bg-white px-4 py-2">
          <button type="button" ref={openButton} data-testid="open-conversations" aria-label={t.openConversations}
            aria-expanded={listOpen} aria-controls="conversation-list" onClick={() => setListOpen(true)}
            className="inline-flex h-10 w-10 items-center justify-center rounded border text-base hover:bg-slate-100 md:hidden">
            ☰
          </button>
          <span data-testid="conversation-title" className="min-w-0 flex-1 truncate text-sm font-medium md:hidden">
            {openTitle}
          </span>
          <select value={provider} onChange={(e) => { picked.current = true; setProvider(e.target.value) }}
            disabled={!!activeId} title={activeId ? t.providerLocked : undefined}
            data-testid="provider-select"
            className="h-10 border rounded px-2 py-1 text-base md:h-auto md:text-sm disabled:bg-slate-100 disabled:text-slate-600 disabled:opacity-100">
            {PROVIDERS.map((p) => (
              <option key={p} value={p} disabled={served[p] === false}>
                {served[p] === false ? `${p} (${t.providerIdle})` : p}
              </option>
            ))}
          </select>
          {mediaCount >= 2 && (
            <button type="button" data-testid="download-all" onClick={() => saveZip()}
              disabled={packing}
              className="rounded border px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50">
              {packing ? t.packing : t.downloadAll(mediaCount)}
            </button>
          )}
          {error && <span className="text-sm text-red-600">{error}</span>}
        </header>

        <div ref={scrollRef} onScroll={trackScroll} data-testid="message-scroll"
          className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50">
          {!conversation && <p className="text-slate-400 text-sm">{t.startHint}</p>}

          {timeline.map((entry) =>
            entry.kind === 'media' ? (
              <div key={entry.id} className="flex flex-col items-start gap-2">
                <MediaCard item={entry.media} busy={!!status || unserved} label={t.videoScript}
                  onOpen={open} onScript={requestScript} />
              </div>
            ) : (
              <div key={entry.id} className={`flex flex-col gap-2 ${
                entry.message.role === 'user' ? 'items-end' : 'items-start'}`}>
                {entry.message.content && (
                  entry.message.role === 'user' ? (
                    <div data-testid="user-bubble"
                      className="max-w-[min(42rem,100%)] whitespace-pre-wrap rounded-lg bg-slate-900 px-3 py-2 text-sm text-white [overflow-wrap:anywhere]">
                      {entry.message.content}
                    </div>
                  ) : (
                    <ReplyText text={entry.message.content} />
                  )
                )}
                {entry.message.media?.map((item) => (
                  <MediaCard key={item.id} item={item} busy={!!status || unserved} label={t.videoScript}
                    onOpen={open} onScript={requestScript} />
                ))}
                {(entry.message.media?.length || 0) >= 2 && (
                  <button type="button" data-testid="download-message" disabled={packing}
                    onClick={() => saveZip(entry.message.id)}
                    className="text-xs text-slate-500 underline hover:text-slate-900 disabled:opacity-50">
                    {t.downloadThese(entry.message.media.length)}
                  </button>
                )}
              </div>
            )
          )}

          {status && <TypingBubble hint={pendingHint} phase={phase} />}
        </div>

        <Lightbox url={viewing?.url} filename={viewing?.filename}
          onClose={() => setViewing(null)} />

        {/* The live region stays in the page, so a screen reader hears the notice arrive. */}
        <div role="status">
          {unserved && (
            <p id="provider-unserved" data-testid="provider-unserved"
              className="border-t bg-amber-50 px-4 py-2 text-sm text-amber-800">
              {t.providerUnserved(provider, anotherServed, !!activeId)}
            </p>
          )}
        </div>
        <form onSubmit={send} className="flex gap-2 border-t bg-white p-3">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            placeholder={t.composer} aria-describedby={unserved ? 'provider-unserved' : undefined}
            className="min-w-0 flex-1 border rounded px-3 py-2 text-base md:text-sm" />
          {status ? (
            <button type="button" onClick={stopJob}
              className="rounded bg-red-600 px-4 text-sm text-white hover:bg-red-700">
              {t.stop}
            </button>
          ) : (
            <button type="submit" disabled={unserved}
              className="bg-slate-900 text-white rounded px-4 text-sm disabled:opacity-50">
              {t.send}
            </button>
          )}
        </form>
      </section>
    </div>
  )
}
