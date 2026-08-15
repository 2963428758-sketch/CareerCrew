import { useEffect, useState, useSyncExternalStore } from "react"
import { apiFetch } from "@/lib/auth"

/**
 * 头像加载：受保护资源（Authorization 头无法挂在 <img> 上），
 * 统一经 apiFetch 取回 Blob 并缓存对象 URL（与知识库图片同一模式）。
 * 上传成功后调用 bumpAvatarNonce() 使所有头像组件失效重取。
 */

let nonce = 0
const listeners = new Set<() => void>()

const blobCache = new Map<string, string>() // userId -> objectURL

export function getAvatarNonce() {
  return nonce
}

export function subscribeAvatar(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function bumpAvatarNonce() {
  nonce += 1
  // 上传后旧 blob 指向旧头像：清空对象 URL 缓存，强制所有头像组件重新拉取
  for (const url of blobCache.values()) {
    try {
      URL.revokeObjectURL(url)
    } catch {
      // 已失效的 URL 忽略
    }
  }
  blobCache.clear()
  listeners.forEach((l) => l())
}

function cached(userId: string) {
  return blobCache.get(userId) ?? null
}

/** 返回用户头像的 blob URL；无头像/加载失败返回 null（组件回退到首字母色块）。 */
export function useAvatar(userId: string | undefined) {
  const version = useSyncExternalStore(subscribeAvatar, getAvatarNonce, getAvatarNonce)
  const [url, setUrl] = useState<string | null>(() => (userId ? cached(userId) : null))

  useEffect(() => {
    if (!userId) {
      setUrl(null)
      return
    }
    const hit = cached(userId)
    if (hit) {
      setUrl(hit)
      return
    }
    // 缓存未命中：先回退到首字母色块，拉取成功后替换
    setUrl(null)
    let disposed = false
    apiFetch(`/api/auth/avatar/${encodeURIComponent(userId)}`)
      .then(async (r) => {
        if (!r.ok || disposed) return
        if (!(r.headers.get("content-type") || "").startsWith("image/")) return
        const u = URL.createObjectURL(await r.blob())
        if (disposed) {
          URL.revokeObjectURL(u)
          return
        }
        blobCache.set(userId, u)
        setUrl(u)
      })
      .catch(() => {})
    return () => {
      disposed = true
    }
  }, [userId, version])

  return url
}
