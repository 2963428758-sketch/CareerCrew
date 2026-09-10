import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { globalSearch, type SearchItem } from '@/lib/career'
import { networkErrorText } from '@/lib/errors'

export function CareerSearch({ onToast }: { onToast: (message: string) => void }) {
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [items, setItems] = useState<SearchItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const load = async (more: boolean) => {
    const current = ++generation.current
    const keyword = more ? submitted : query.trim()
    setBusy(true)
    try {
      const page = await globalSearch(keyword, more ? cursor ?? undefined : undefined)
      if (current !== generation.current) return
      setSubmitted(keyword)
      setItems(previous => more ? [...previous, ...page.items] : page.items)
      setCursor(page.next_cursor)
    } catch (error) { onToast(networkErrorText(error)) }
    finally { if (current === generation.current) setBusy(false) }
  }
  const destinations: Record<string, string> = {
    opportunities: '/preparation', materials: '/career', real_interviews: '/career', offers: '/career', tasks: '/career',
  }
  return <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
    <p className="font-[560] text-ink">全局搜索（公司 / 岗位 / 素材 / 任务）</p>
    <form className="mt-2 flex gap-2" onSubmit={event => { event.preventDefault(); void load(false) }}>
      <Input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索关键词" aria-label="搜索关键词" />
      <Button type="submit" disabled={busy || !query.trim()}>搜索</Button>
    </form>
    <ul aria-live="polite" className="mt-2 space-y-2">
      {items.map(item => <li key={`${item.kind}:${item.id}`}>
        <Link to={`${destinations[item.kind] ?? '/career'}?${item.kind === 'opportunities' ? 'opportunity' : 'record'}=${encodeURIComponent(item.id)}`}>
          {item.title || '未命名记录'}
        </Link>
        <p className="text-xs text-ink-faint">{item.summary}</p>
      </li>)}
    </ul>
    {submitted && !items.length && <p>没有匹配的记录</p>}
    {cursor && <Button disabled={busy} onClick={() => void load(true)}>加载更多</Button>}
  </div>
}
