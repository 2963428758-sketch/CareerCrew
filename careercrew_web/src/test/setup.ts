// jsdom 测试环境桩：浏览器 API 在 jsdom 中缺失的最小实现。
import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"

if (typeof Element !== "undefined" && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function () {}
}

afterEach(() => cleanup())
