import { expect, it, vi } from 'vitest'
const request = vi.hoisted(() => vi.fn().mockResolvedValue({ ok: true }))
vi.mock('@/lib/auth', () => ({ apiFetch: request }))
import { trackProductEvent } from './productEvents'
it('sends only content-free event fields and does not throw on failure', async () => {
  await trackProductEvent('material_copied', 'preparation')
  const payload = JSON.parse(request.mock.calls[0][1].body)
  expect(Object.keys(payload).sort()).toEqual(['event', 'event_id', 'source'])
  expect(payload.event).toBe('material_copied')
  request.mockRejectedValueOnce(new Error('offline'))
  await expect(trackProductEvent('material_saved', 'preparation')).resolves.toBeUndefined()
})
