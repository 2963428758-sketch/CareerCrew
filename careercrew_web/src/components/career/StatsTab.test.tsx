// @vitest-environment jsdom
import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { StatsTab } from './StatsTab'
vi.mock('@/lib/career', () => ({
  getStats: async () => ({ applied: 0, replies: 0, interviewed: 0, offers: 0, by_source: {}, by_version: {}, by_stage: {}, tasks: { open: 0 }, reply_rate: { numerator: 0, denominator: 0, rate: null }, interview_rate: { numerator: 0, denominator: 0, rate: null }, offer_rate: { numerator: 0, denominator: 0, rate: null } }),
  getGenerationMetrics: async () => ({ total: 4, fallback_count: 1, fallback_rate: .25, p95_latency_ms: 1200, by_source: { llm: 3, template: 1 } }),
  getProductFunnel: async () => ({ counts: { opportunity_saved: 2, material_saved: 1 }, note: '操作次数统计' }),
}))
afterEach(cleanup)
it('shows generation degradation and privacy-safe pilot events', async () => {
  render(<StatsTab />)
  await screen.findByText(/AI 生成运行情况/)
  expect(screen.getByText(/降级 1\/4/)).toBeTruthy()
  expect(screen.getByText(/保存岗位 2/)).toBeTruthy()
  expect(screen.getByText(/操作次数统计/)).toBeTruthy()
})
