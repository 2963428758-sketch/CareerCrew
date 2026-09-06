import { describe, expect, it } from "vitest"

import { isSafeHttpUrl, jobsFromMetadata } from "@/lib/preparation"

describe("jobsFromMetadata", () => {
  it("从历史 metadata 解析岗位并丢弃无效项", () => {
    const jobs = jobsFromMetadata({
      jobs: [
        { company: "测试公司", title: "Java开发", url: "https://e.com/1", jd: "负责接口" },
        { company: "", title: "无公司" },
        "not-an-object",
        null,
      ],
    })
    expect(jobs).toHaveLength(1)
    expect(jobs[0].company).toBe("测试公司")
    expect(jobs[0].city).toBe("")
  })

  it("无 metadata 或非数组时返回空数组（旧历史兼容）", () => {
    expect(jobsFromMetadata(null)).toEqual([])
    expect(jobsFromMetadata({ sources: [] })).toEqual([])
    expect(jobsFromMetadata({ jobs: "bad" })).toEqual([])
  })
})

describe("isSafeHttpUrl", () => {
  it("只放行 HTTP/HTTPS 绝对链接", () => {
    expect(isSafeHttpUrl("https://example.com/j/1")).toBe(true)
    expect(isSafeHttpUrl("http://example.com")).toBe(true)
    expect(isSafeHttpUrl("javascript:alert(1)")).toBe(false)
    expect(isSafeHttpUrl("file:///private")).toBe(false)
    expect(isSafeHttpUrl("//example.com")).toBe(false)
    expect(isSafeHttpUrl("")).toBe(false)
    expect(isSafeHttpUrl("https://exa mple.com")).toBe(false)
  })
})
