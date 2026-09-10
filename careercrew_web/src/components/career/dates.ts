export function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

export function isOverdue(due: string): boolean {
  return Boolean(due) && due < todayStr()
}

/** 日期输入的通用格式提示。 */
export const DATE_HINT = "格式 YYYY-MM-DD"

