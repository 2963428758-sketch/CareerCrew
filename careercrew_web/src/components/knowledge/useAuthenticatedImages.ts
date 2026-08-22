import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/auth"

export type AuthenticatedImage = { status: "loading" | "ready" | "error"; url?: string }

export const imageEndpoint = (path: string) =>
  `/api/knowledge/image?path=${encodeURIComponent(path.replace(/\\/g, "/"))}`

/**
 * <img> 不能携带 Authorization 请求头，所以先通过 apiFetch 取回受保护图片，
 * 再把 Blob URL 交给图片元素。每轮请求产生的 URL 都会在替换或卸载时释放。
 */
export function useAuthenticatedImages(paths: readonly (string | undefined)[]) {
  const signature = [...new Set(paths.filter((path): path is string => Boolean(path)))].sort().join("\u0000")

  const [images, setImages] = useState<Record<string, AuthenticatedImage>>({})

  useEffect(() => {
    const uniquePaths = signature ? signature.split("\u0000") : []
    if (uniquePaths.length === 0) {
      setImages({})
      return
    }

    let disposed = false
    const objectUrls: string[] = []
    setImages(Object.fromEntries(uniquePaths.map((path) => [path, { status: "loading" }])) as Record<string, AuthenticatedImage>)

    void Promise.all(uniquePaths.map(async (path) => {
      try {
        const response = await apiFetch(imageEndpoint(path))
        if (!response.ok) throw new Error(`Image request failed: ${response.status}`)
        if (!response.headers.get("Content-Type")?.startsWith("image/")) {
          throw new Error("Image request returned a non-image response")
        }
        const url = URL.createObjectURL(await response.blob())
        objectUrls.push(url)
        return [path, { status: "ready", url }] as const
      } catch {
        return [path, { status: "error" }] as const
      }
    })).then((entries) => {
      if (disposed) return
      setImages(Object.fromEntries(entries))
    })

    return () => {
      disposed = true
      objectUrls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [signature])

  return images
}

export function imagePathsIn(text: string): string[] {
  return [...text.matchAll(/^\[image:\s*(.+?)\]\s*$/gm)].map((match) => match[1])
}

/** 把 rag_query 返回的 [image: 绝对路径] 行转为已鉴权的 Blob 图片。 */
export function renderKnowledgeText(text: string, images: Record<string, AuthenticatedImage>): string {
  return text.replace(/^\[image:\s*(.+?)\]\s*$/gm, (_m, rawPath: string) => {
    const image = images[rawPath]
    if (image?.status === "ready" && image.url) return `![知识库图片](${image.url})`
    return image?.status === "error" ? "知识库图片加载失败。" : "知识库图片加载中…"
  })
}
