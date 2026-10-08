const BASE = import.meta.env.VITE_API_URL || 'http://localhost:3000'
export const apiBase = BASE

let token = localStorage.getItem('token') || null

export function getToken() {
  return token
}

export function setToken(next) {
  token = next
  if (next) localStorage.setItem('token', next)
  else localStorage.removeItem('token')
}

async function request(method, path, body) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401) {
    setToken(null)
    throw new Error('session expired, sign in again')
  }
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
  conversations: (q) => request('GET', q ? `/conversations?q=${encodeURIComponent(q)}` : '/conversations'),
  conversation: (id) => request('GET', `/conversations/${id}`),
  renameConversation: (id, title) => request('PATCH', `/conversations/${id}`, { title }),
  deleteConversation: (id) => request('DELETE', `/conversations/${id}`),
  chat: (payload) => request('POST', '/chat', payload),
  videoScript: (payload) => request('POST', '/video/script', payload),
  job: (id) => request('GET', `/jobs/${id}`),
  cancelJob: (id) => request('POST', `/jobs/${id}/cancel`),
  providers: () => request('GET', '/providers'),
  media: () => request('GET', '/media'),
  deleteMedia: (id) => request('DELETE', `/media/${id}`),
  apiKeys: () => request('GET', '/auth/api-keys'),
  createApiKey: (name) => request('POST', '/auth/api-keys', { name }),
  revokeApiKey: (id) => request('DELETE', `/auth/api-keys/${id}`),
}

export async function mediaBlobUrl(id) {
  const response = await fetch(`${BASE}/media/${id}/file`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw new Error('could not load image')
  return URL.createObjectURL(await response.blob())
}

// One archive of everything a conversation, or one message of it, produced.
// Returns a blob url and the file name the server chose.
export async function conversationZipUrl(conversationId, messageId) {
  const query = messageId ? `?message_id=${encodeURIComponent(messageId)}` : ''
  const response = await fetch(`${BASE}/conversations/${conversationId}/media.zip${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw new Error(`could not build the archive (${response.status})`)
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
      failure.kind = job.error_kind
      throw failure
    }
    if (onTick) onTick(job.status, job.phase)
    await new Promise((resolve) => setTimeout(resolve, 1500))
  }
}
