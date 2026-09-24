import { createContext, useContext, useMemo, useState } from 'react'

// Every string a person reads, in the two languages the team uses. The tests
// run in an English browser and keep matching the English labels.
const STRINGS = {
  en: {
    appName: 'AI Platform',
    chat: 'chat',
    gallery: 'gallery',
    signOut: 'sign out',
    left: 'left',
    language: 'VI',
    loading: 'loading...',
    newChat: 'New chat',
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
    replyLanded: 'Your reply is ready.',
    download: 'Download',
    preparing: 'Preparing...',
    close: 'Close',
    galleryTitle: (n) => `Gallery (${n})`,
    nothingYet: 'Nothing generated yet.',
    signIn: 'Sign in',
    createAccount: 'Create account',
    email: 'email',
    password: 'password',
    nameOptional: 'name (optional)',
    inviteCode: 'invite code',
    working: 'working...',
  },
  vi: {
    appName: 'AI Platform',
    chat: 'trò chuyện',
    gallery: 'thư viện',
    signOut: 'đăng xuất',
    left: 'lượt',
    language: 'EN',
    loading: 'đang tải...',
    newChat: 'Trò chuyện mới',
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
    replyLanded: 'Đã có trả lời.',
    download: 'Tải về',
    preparing: 'Đang chuẩn bị...',
    close: 'Đóng',
    galleryTitle: (n) => `Thư viện (${n})`,
    nothingYet: 'Chưa tạo gì cả.',
    signIn: 'Đăng nhập',
    createAccount: 'Tạo tài khoản',
    email: 'email',
    password: 'mật khẩu',
    nameOptional: 'tên (không bắt buộc)',
    inviteCode: 'mã mời',
    working: 'đang xử lý...',
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
