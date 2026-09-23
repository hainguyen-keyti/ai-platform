const BASE = import.meta.env.VITE_API_URL || 'http://localhost:3000'

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
    throw new Error(typeof detail === 'string' ? detail : `request failed (${response.status})`)
  }
  return data
}

export const api = {
  login: (email, password) => request('POST', '/auth/login', { email, password }),
  register: (email, password, name, invite_code) =>
    request('POST', '/auth/register', { email, password, name, invite_code }),
  me: () => request('GET', '/auth/me'),
  conversations: () => request('GET', '/conversations'),
  conversation: (id) => request('GET', `/conversations/${id}`),
  deleteConversation: (id) => request('DELETE', `/conversations/${id}`),
  chat: (payload) => request('POST', '/chat', payload),
  videoScript: (payload) => request('POST', '/video/script', payload),
  job: (id) => request('GET', `/jobs/${id}`),
  media: () => request('GET', '/media'),
  deleteMedia: (id) => request('DELETE', `/media/${id}`),
}

export async function mediaBlobUrl(id) {
  const response = await fetch(`${BASE}/media/${id}/file`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw new Error('could not load image')
  return URL.createObjectURL(await response.blob())
}

export async function waitForJob(jobId, onTick) {
  for (;;) {
    const job = await api.job(jobId)
    if (job.status === 'done') return job
    if (job.status === 'failed') throw new Error(job.error || 'job failed')
    if (onTick) onTick(job.status)
    await new Promise((resolve) => setTimeout(resolve, 1500))
  }
}
