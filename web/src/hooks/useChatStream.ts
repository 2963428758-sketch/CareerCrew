import { useCallback, useRef, useState } from "react"
import type { KnowledgeSource, StreamEvent, StreamStatus } from "@/types"

/**
 * 核心 hook：fetch POST + ReadableStream 读 NDJSON，按行解析事件。
 *
 * - 返回 { events, status, streamingText, thinking, start, stop }
 * - stop 用 AbortController
 * - thinking: 流式中 2 秒无新 chunk → true（初始化 / 工具调用等待）
 */
export function useChatStream() {
  const [status, setStatus] = useState<StreamStatus>("idle")
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [streamingText, setStreamingText] = useState("")
  const [agentChunks, setAgentChunks] = useState<Record<string, string>>({})
  const [stage, setStage] = useState<string>("")
  const [doneContent, setDoneContent] = useState("")
  const [opinions, setOpinions] = useState<Record<string, string>>({})
  const [doneSources, setDoneSources] = useState<KnowledgeSource[]>([])
  const [errorMsg, setErrorMsg] = useState("")
  /** 流式中 2 秒无新 chunk → true（区分初始化 vs 工具调用） */
  const [thinking, setThinking] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const thinkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const reset = useCallback(() => {
    setEvents([])
    setStreamingText("")
    setAgentChunks({})
    setStage("")
    setDoneContent("")
    setOpinions({})
    setDoneSources([])
    setErrorMsg("")
    setThinking(false)
    setStatus("idle")
    if (thinkTimerRef.current) clearTimeout(thinkTimerRef.current)
  }, [])

  const armThinkingTimer = useCallback(() => {
    if (thinkTimerRef.current) clearTimeout(thinkTimerRef.current)
    thinkTimerRef.current = setTimeout(() => setThinking(true), 2000)
  }, [])

  const disarmThinkingTimer = useCallback(() => {
    if (thinkTimerRef.current) {
      clearTimeout(thinkTimerRef.current)
      thinkTimerRef.current = null
    }
    setThinking(false)
  }, [])

  const start = useCallback(async (endpoint: string, body: Record<string, unknown>) => {
    setEvents([])
    setStreamingText("")
    setAgentChunks({})
    setStage("")
    setDoneContent("")
    setOpinions({})
    setDoneSources([])
    setErrorMsg("")
    setThinking(false)
    setStatus("streaming")
    armThinkingTimer() // 2 秒后若无 chunk → thinking

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const resp = await fetch(`/api${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!resp.ok) {
        const text = await resp.text().catch(() => "")
        throw new Error(`HTTP ${resp.status}: ${text}`)
      }

      const reader = resp.body?.getReader()
      if (!reader) throw new Error("无法获取响应流")

      const decoder = new TextDecoder()
      let buffer = ""
      let textAccum = ""
      const agentAccum: Record<string, string> = {}

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const evt = JSON.parse(trimmed) as StreamEvent
            setEvents((prev) => [...prev, evt])

            if (evt.type === "stage") {
              setStage(evt.stage)
            } else if (evt.type === "chunk") {
              // 收到 chunk → 重置 thinking 计时器
              disarmThinkingTimer()
              armThinkingTimer()

              if (evt.agent) {
                agentAccum[evt.agent] = (agentAccum[evt.agent] ?? "") + evt.text
                setAgentChunks({ ...agentAccum })
              } else {
                textAccum += evt.text
                setStreamingText(textAccum)
              }
            } else if (evt.type === "agent_start" || evt.type === "agent_end") {
              disarmThinkingTimer()
              armThinkingTimer()
            } else if (evt.type === "done") {
              setDoneContent(evt.content)
              if (evt.opinions) setOpinions(evt.opinions)
              if (evt.sources) setDoneSources(evt.sources)
              setStatus("done")
            } else if (evt.type === "error") {
              setErrorMsg(evt.message)
              setStatus("error")
            }
          } catch {
            // 忽略解析失败的行
          }
        }
      }

      setStatus((prev) => (prev === "streaming" ? "done" : prev))
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        setStatus("idle")
        return
      }
      setErrorMsg((e as Error).message)
      setStatus("error")
    } finally {
      disarmThinkingTimer()
      abortRef.current = null
    }
  }, [armThinkingTimer, disarmThinkingTimer])

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return {
    status,
    events,
    streamingText,
    agentChunks,
    stage,
    doneContent,
    opinions,
    doneSources,
    errorMsg,
    /** 流式中 2 秒无新 chunk → true */
    thinking,
    /** 流式中且尚未收到任何 chunk → 初始化阶段 */
    initializing: status === "streaming" && streamingText === "" && Object.keys(agentChunks).length === 0,
    start,
    stop,
    reset,
  }
}
