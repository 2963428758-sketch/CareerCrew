import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { getProfile, saveProfile } from "@/lib/career"

const STAGE_OPTIONS = ["在校求职", "应届秋招/春招", "在职看机会", "离职求职"]

/**
 * 首次使用引导：确认求职阶段、城市与目标，只收集 3 个字段；
 * 可跳过（不再自动弹出，可在求职中心重做——再次保存即视为完成）。
 */
export function OnboardingDialog() {
  const [open, setOpen] = useState(false)
  const [stage, setStage] = useState("")
  const [city, setCity] = useState("")
  const [goal, setGoal] = useState("")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    getProfile()
      .then((profile) => {
        if (cancelled || profile?.onboarding_done) return
        setOpen(true)
        if (profile) {
          setStage(profile.stage || "")
          setCity(profile.city || "")
          setGoal(profile.goal || "")
        }
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  const submit = async (onboardingDone: boolean) => {
    if (saving) return
    setSaving(true)
    try {
      await saveProfile({ stage, city, goal, onboarding_done: onboardingDone })
    } catch {
      // 保存失败不打断：引导关闭，下次仍可完善
    } finally {
      setSaving(false)
      setOpen(false)
    }
  }

  if (!open) return null
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-[440px] rounded-[12px] border border-[var(--border-soft)] bg-workspace p-5 shadow-lg">
        <h2 className="text-[15px] font-[600] text-ink">欢迎使用 CareerCrew</h2>
        <p className="mt-1 text-[12.5px] text-ink-faint">
          用 30 秒确认求职背景，各顾问会以此为准；之后可随时在「求职中心」重做。
        </p>
        <div className="mt-3.5 flex flex-col gap-3">
          <div>
            <p className="mb-1 text-[12.5px] text-ink-soft">当前求职阶段</p>
            <div className="flex flex-wrap gap-1.5">
              {STAGE_OPTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStage(s)}
                  className={
                    "rounded-full border px-3 py-1 text-[12px] transition-colors " +
                    (stage === s
                      ? "border-ink/50 bg-surface-2 font-[560] text-ink"
                      : "border-[var(--border-soft)] text-ink-faint hover:border-ink-faint/60 hover:text-ink")
                  }
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
            目标城市
            <Input value={city} onChange={(e) => setCity(e.target.value)} placeholder="例如：深圳" className="h-[32px]" maxLength={100} />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
            目标方向 / 岗位
            <Input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="例如：大模型应用工程师" className="h-[32px]" maxLength={1000} />
          </label>
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" className="text-[12.5px]" disabled={saving} onClick={() => void submit(true)}>
            跳过
          </Button>
          <Button size="sm" disabled={saving} onClick={() => void submit(true)}>
            {saving ? "保存中…" : "完成引导"}
          </Button>
        </div>
      </div>
    </div>
  )
}
