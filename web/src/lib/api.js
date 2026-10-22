const BASE = import.meta.env.VITE_API_URL || 'http://localhost:3000'
export const apiBase = BASE
export const MEDIA_PAGE = 100

let token = localStorage.getItem('token') || null

export function getToken() {
  return token
}

export function setToken(next) {
  token = next
  if (next) localStorage.setItem('token', next)
  else localStorage.removeItem('token')
}

// The shell is told the moment the api refuses the login, whichever call it was.
let onUnauthorized = null

export function whenUnauthorized(handler) {
  onUnauthorized = handler
}

// A refusal of an older token (a poll still running from before a new sign-in) leaves the new one be.
function expired(sent) {
  if (token === sent) {
    setToken(null)
    if (onUnauthorized) onUnauthorized()
  }
  const failure = new Error('session expired, sign in again')
  failure.status = 401
  return failure
}

async function request(method, path, body) {
  const sent = token
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (sent) headers['Authorization'] = `Bearer ${sent}`

  const response = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401) throw expired(sent)
  if (response.status === 204) return null

  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) {
    const detail = data && data.detail
    const failure = new Error(typeof detail === 'string' ? detail : `request failed (${response.status})`)
    failure.status = response.status
    throw failure
  }
  return data
}

export const api = {
  login: (email, password) => request('POST', '/auth/login', { email, password }),
  register: (email, password, name, invite_code) =>
    request('POST', '/auth/register', { email, password, name, invite_code }),
  me: () => request('GET', '/auth/me'),
  logout: () => request('POST', '/auth/logout'),
  conversations: (q) => request('GET', q ? `/conversations?q=${encodeURIComponent(q)}` : '/conversations'),
  conversation: (id) => request('GET', `/conversations/${id}`),
  renameConversation: (id, title) => request('PATCH', `/conversations/${id}`, { title }),
  deleteConversation: (id) => request('DELETE', `/conversations/${id}`),
  chat: (payload) => request('POST', '/chat', payload),
  videoScript: (payload) => request('POST', '/video/script', payload),
  job: (id) => request('GET', `/jobs/${id}`),
  cancelJob: (id) => request('POST', `/jobs/${id}/cancel`),
  providers: () => request('GET', '/providers'),
  media: (offset = 0) => request('GET', `/media?limit=${MEDIA_PAGE}&offset=${offset}`),
  deleteMedia: (id) => request('DELETE', `/media/${id}`),
  apiKeys: () => request('GET', '/auth/api-keys'),
  createApiKey: (name) => request('POST', '/auth/api-keys', { name }),
  revokeApiKey: (id) => request('DELETE', `/auth/api-keys/${id}`),
}

export async function mediaBlobUrl(id) {
  const sent = token
  const response = await fetch(`${BASE}/media/${id}/file`, {
    headers: { Authorization: `Bearer ${sent}` },
  })
  if (response.status === 401) throw expired(sent)
  if (!response.ok) throw new Error('could not load image')
  return URL.createObjectURL(await response.blob())
}

// One archive of everything a conversation, or one message of it, produced.
// Returns a blob url and the file name the server chose.
export async function conversationZipUrl(conversationId, messageId) {
  const query = messageId ? `?message_id=${encodeURIComponent(messageId)}` : ''
  const sent = token
  const response = await fetch(`${BASE}/conversations/${conversationId}/media.zip${query}`, {
    headers: { Authorization: `Bearer ${sent}` },
  })
  if (response.status === 401) throw expired(sent)
  if (!response.ok) {
    const failure = new Error(`could not build the archive (${response.status})`)
    failure.status = response.status
    throw failure
  }
  const match = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')
  return {
    url: URL.createObjectURL(await response.blob()),
    filename: match ? match[1] : `conversation-${conversationId.slice(0, 8)}.zip`,
  }
}

export async function waitForJob(jobId, onTick) {
  for (;;) {
    const job = await api.job(jobId)
    if (job.status === 'done' || job.status === 'cancelled') return job
    if (job.status === 'failed') {
      const failure = new Error(job.error || 'job failed')
      failure.kind = job.error_kind || 'failed'
      throw failure
    }
    if (onTick) onTick(job.status, job.phase)
    await new Promise((resolve) => setTimeout(resolve, 1500))
  }
}
