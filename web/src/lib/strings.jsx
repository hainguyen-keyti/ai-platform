import { createContext, useContext, useMemo, useState } from 'react'

// Every string a person reads, in the two languages the team uses. The tests
// run in an English browser and keep matching the English labels.
const STRINGS = {
  en: {
    appName: 'AI Platform',
    chat: 'chat',
    gallery: 'gallery',
    signOut: 'sign out',
    left: (n) => `${n} left`,
    language: 'VI',
    loading: 'loading...',
    locale: 'en-US',
    offline: 'Could not reach the server. Check your connection, then try again.',
    retry: 'Try again',
    turnFailed: 'This request failed; your credit was returned. Please try again.',
    noCredit: (time) => `You have no credits left. They come back at ${time}.`,
    notFound: 'Not found: it may have just been deleted.',
    otherProvider: 'This conversation belongs to another provider. Start a new chat to use this one.',
    refusedInput: 'The message was refused: it is empty or too long.',
    serverFailed: 'The server ran into a problem. Please try again.',
    jobElsewhere: 'A reply is still coming in another conversation. You can send when it is done.',
    openIt: 'Open it',
    phases: {
      'retrying the composer': 'trying again',
      requeued: 'trying again',
      'reply started': 'writing the reply',
      'reply finished': 'reply written',
      'making a video': 'making the video',
      'picture appeared': 'picture ready, fetching it',
      'video appeared': 'video ready, fetching it',
      'file appeared': 'file ready, fetching it',
    },
    newChat: 'New chat',
    conversations: 'Conversations',
    openConversations: 'Open conversations',
    noConversations: 'No conversations yet.',
    noMatch: 'No conversation matches.',
    provider: 'Provider',
    untitled: 'Untitled',
    startHint: 'Start a new conversation.',
    composer: 'Type a message, or ask for a picture...',
    send: 'Send',
    stop: 'Stop',
    packing: 'Packing...',
    downloadAll: (n) => `Download all (${n})`,
    downloadThese: (n) => `Download these ${n} as one zip`,
    videoScript: 'Video script',
    rename: 'Rename',
    delete: 'Delete',
    confirmDelete: 'Delete this conversation with its pictures and files? This cannot be undone.',
    search: 'Search conversations',
    slowHint: 'Still working. Asking for a picture takes the longest.',
    providerLocked: 'This conversation belongs to this provider. Start a new chat to use another.',
    providerIdle: 'unavailable',
    // other: another provider is served; inChat: a conversation is open (its provider is fixed).
    providerUnserved: (p, other, inChat) => `Sending is paused: ${p} is unavailable right now. Try again later${
      other ? (inChat ? ', or start a new chat with another provider' : ', or pick another provider') : ''}.`,
    replyLanded: 'Your reply is ready.',
    download: 'Download',
    preparing: 'Preparing...',
    videoLabel: 'Generated video',
    videoFailed: 'Could not load this video.',
    close: 'Close',
    galleryTitle: (n) => `Gallery (${n})`,
    nothingYet: 'Nothing generated yet.',
    galleryHeading: 'Gallery',
    confirmDeleteMedia: 'Delete this file for good? It also disappears from its conversation. This cannot be undone.',
    showMore: (n) => `Show more (${n} left)`,
    signIn: 'Sign in',
    createAccount: 'Create account',
    email: 'email',
    password: 'password',
    nameOptional: 'name (optional)',
    inviteCode: 'invite code',
    working: 'working...',
    api: 'API',
    apiKeysTitle: 'API keys',
    apiKeysIntro: 'A key lets your own scripts or tools make pictures with ChatGPT, spending your credits. Keep it secret, and revoke it if it leaks.',
    keyName: 'Key name',
    keyNamePlaceholder: 'what it is for, e.g. my script',
    createKey: 'Create key',
    newKeyFor: (name) => `New key "${name}"`,
    keyShownOnce: 'Copy this key now: it is shown only this once.',
    copy: 'Copy',
    copied: 'Copied',
    copyFailed: 'Could not copy. Select the key and copy it by hand.',
    keyDone: 'Done, I saved it',
    yourKeys: 'Your keys',
    noKeys: 'No keys yet.',
    keyCreated: (d) => `made ${d}`,
    keyUsed: (d) => `last used ${d}`,
    keyNeverUsed: 'never used',
    revoke: 'Revoke',
    confirmRevoke: (name) => `Revoke the key "${name}"? Programs using it stop working at once.`,
    howToCall: 'How to call it',
    howToCallNote: 'The first call answers at once with an id. Ask again with it until the status is done, then download each picture from its url. The image line is optional.',
  },
  vi: {
    appName: 'AI Platform',
    chat: 'trò chuyện',
    gallery: 'thư viện',
    signOut: 'đăng xuất',
    left: (n) => `còn ${n}`,
    language: 'EN',
    loading: 'đang tải...',
    locale: 'vi-VN',
    offline: 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.',
    retry: 'Thử lại',
    turnFailed: 'Yêu cầu này không thành công, bạn đã được hoàn lại 1 lượt. Hãy thử lại.',
    noCredit: (time) => `Bạn đã hết lượt. Lượt được cấp lại lúc ${time}.`,
    jobElsewhere: 'Một cuộc trò chuyện khác đang chờ trả lời. Bạn gửi được khi nó xong.',
    openIt: 'Mở cuộc trò chuyện đó',
    notFound: 'Không tìm thấy: có thể nó vừa bị xoá.',
    otherProvider: 'Cuộc trò chuyện này thuộc nhà cung cấp khác. Hãy mở trò chuyện mới để dùng bên này.',
    refusedInput: 'Tin nhắn bị từ chối: trống hoặc quá dài.',
    serverFailed: 'Máy chủ gặp lỗi. Hãy thử lại.',
    phases: {
      waiting: 'đang chờ',
      'waiting for the provider': 'đang chờ nhà cung cấp',
      'retrying the composer': 'đang thử lại',
      requeued: 'đang thử lại',
      'reply started': 'đang viết câu trả lời',
      'reply finished': 'đã viết xong',
      'making a video': 'đang làm video',
      'picture appeared': 'đã có ảnh, đang lấy về',
      'video appeared': 'đã có video, đang lấy về',
      'file appeared': 'đã có tệp, đang lấy về',
    },
    newChat: 'Trò chuyện mới',
    conversations: 'Các cuộc trò chuyện',
    openConversations: 'Mở danh sách trò chuyện',
    noConversations: 'Chưa có cuộc trò chuyện nào.',
    noMatch: 'Không tìm thấy cuộc trò chuyện nào.',
    provider: 'Nhà cung cấp',
    untitled: 'Chưa đặt tên',
    startHint: 'Bắt đầu một cuộc trò chuyện mới.',
    composer: 'Nhập tin nhắn, hoặc yêu cầu một bức hình...',
    send: 'Gửi',
    stop: 'Dừng',
    packing: 'Đang gói...',
    downloadAll: (n) => `Tải tất cả (${n})`,
    downloadThese: (n) => `Tải ${n} tệp này thành một zip`,
    videoScript: 'Kịch bản video',
    rename: 'Đổi tên',
    delete: 'Xoá',
    confirmDelete: 'Xoá cuộc trò chuyện này cùng hình và tệp của nó? Không thể hoàn tác.',
    search: 'Tìm cuộc trò chuyện',
    slowHint: 'Vẫn đang làm. Tạo hình mất lâu nhất.',
    providerLocked: 'Cuộc trò chuyện này thuộc về nhà cung cấp đang chọn. Mở trò chuyện mới để dùng bên khác.',
    providerIdle: 'tạm ngưng',
    providerUnserved: (p, other, inChat) => `Chưa gửi được: ${p} đang tạm ngưng. Hãy thử lại sau${
      other ? (inChat ? ', hoặc mở trò chuyện mới với nhà cung cấp khác' : ', hoặc chọn nhà cung cấp khác') : ''}.`,
    replyLanded: 'Đã có trả lời.',
    download: 'Tải về',
    preparing: 'Đang chuẩn bị...',
    videoLabel: 'Video đã tạo',
    videoFailed: 'Không tải được video.',
    close: 'Đóng',
    galleryTitle: (n) => `Thư viện (${n})`,
    nothingYet: 'Chưa tạo gì cả.',
    galleryHeading: 'Thư viện',
    confirmDeleteMedia: 'Xoá vĩnh viễn tệp này? Nó cũng biến mất khỏi cuộc trò chuyện. Không thể hoàn tác.',
    showMore: (n) => `Xem thêm (còn ${n})`,
    signIn: 'Đăng nhập',
    createAccount: 'Tạo tài khoản',
    email: 'email',
    password: 'mật khẩu',
    nameOptional: 'tên (không bắt buộc)',
    inviteCode: 'mã mời',
    working: 'đang xử lý...',
    api: 'API',
    apiKeysTitle: 'Khoá API',
    apiKeysIntro: 'Khoá cho phép script hay công cụ của bạn tạo hình bằng ChatGPT, trừ vào lượt của bạn. Hãy giữ bí mật, và thu hồi ngay nếu bị lộ.',
    keyName: 'Tên khoá',
    keyNamePlaceholder: 'dùng cho việc gì, ví dụ: script của tôi',
    createKey: 'Tạo khoá',
    newKeyFor: (name) => `Khoá mới "${name}"`,
    keyShownOnce: 'Hãy chép khoá này ngay: nó chỉ hiện đúng một lần.',
    copy: 'Chép',
    copied: 'Đã chép',
    copyFailed: 'Không chép được. Hãy chọn khoá rồi tự chép.',
    keyDone: 'Xong, tôi đã lưu',
    yourKeys: 'Khoá của bạn',
    noKeys: 'Chưa có khoá nào.',
    keyCreated: (d) => `tạo ${d}`,
    keyUsed: (d) => `dùng lần cuối ${d}`,
    keyNeverUsed: 'chưa dùng',
    revoke: 'Thu hồi',
    confirmRevoke: (name) => `Thu hồi khoá "${name}"? Chương trình đang dùng nó sẽ ngừng chạy ngay.`,
    howToCall: 'Cách gọi',
    howToCallNote: 'Lần gọi đầu trả về một mã ngay. Dùng mã đó hỏi lại tới khi trạng thái là done, rồi tải từng ảnh theo url của nó. Dòng image là tuỳ chọn.',
  },
}

function initialLanguage() {
  const saved = localStorage.getItem('lang')
  if (saved === 'vi' || saved === 'en') return saved
  return (navigator.language || '').toLowerCase().startsWith('vi') ? 'vi' : 'en'
}

const LanguageContext = createContext({ lang: 'en', t: STRINGS.en, setLang: () => {} })

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(initialLanguage)
  const value = useMemo(() => ({
    lang,
    t: STRINGS[lang],
    setLang: (next) => {
      localStorage.setItem('lang', next)
      setLangState(next)
    },
  }), [lang])
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useStrings() {
  return useContext(LanguageContext)
}

// Credits come back on the first request after midnight UTC, said in the person's own clock.
function refillTime(locale) {
  const now = new Date()
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1))
  return next.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
}

// What a person reads for a failure, in their language; the raw text is kept for a title.
export function failureText(err, t) {
  if (err.kind) return t.turnFailed
  if (err.status === 402) return t.noCredit(refillTime(t.locale))
  if (err.status === 404) return t.notFound
  if (err.status === 409) return t.otherProvider
  if (err.status === 422) return t.refusedInput
  if (err instanceof TypeError) return t.offline
  return t.serverFailed
}
