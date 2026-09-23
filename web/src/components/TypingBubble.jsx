import { useEffect, useState } from 'react'

const HINT_AFTER_SECONDS = 60

function format(seconds) {
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export default function TypingBubble({ hint, phase }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = Date.now()
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div data-testid="typing-bubble">
      <div className="inline-flex flex-col gap-1 rounded-lg border bg-white px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="flex gap-1">
            {[0, 150, 300].map((delay) => (
              <span
                key={delay}
                className="h-2 w-2 animate-bounce rounded-full bg-slate-400"
                style={{ animationDelay: `${delay}ms` }}
              />
            ))}
          </span>
          {/* A real image job runs for minutes; three dots alone are
              indistinguishable from a hung request. */}
          <span className="text-xs tabular-nums text-slate-400">{format(elapsed)}</span>
          {phase && phase !== 'claimed' && (
            <span data-testid="typing-phase" className="text-xs text-slate-500">{phase}</span>
          )}
        </div>
        {hint && elapsed >= HINT_AFTER_SECONDS && (
          <span className="text-xs text-slate-400">{hint}</span>
        )}
      </div>
    </div>
  )
}
