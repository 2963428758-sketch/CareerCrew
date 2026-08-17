/**
 * 会话搜索纯逻辑：前/后循环跳转。
 *
 * 匹配本身不再在此计算：计数与高亮共享“已渲染文本节点”文本域（见
 * searchHighlight.ts 的 `findRenderedMatches`），因此这里仅保留与数据无关的
 * 序号循环跳转纯函数，便于单测。
 */

/**
 * 前/后循环跳转：delta=+1 下一项，-1 上一项；越界回绕。
 * 空匹配集（total === 0）返回 -1；非法当前序号回 0。
 */
export function stepMatch(total: number, currentIndex: number, delta: 1 | -1): number {
  if (total === 0) return -1
  if (currentIndex < 0 || currentIndex >= total) return 0
  return (currentIndex + delta + total) % total
}
