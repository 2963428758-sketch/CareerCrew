// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { SharePanel } from './SharePanel'
import type { Opportunity } from '@/lib/preparation'
const mocks = vi.hoisted(() => ({ create: vi.fn(), list: vi.fn(), revoke: vi.fn() }))
vi.mock('@/lib/career', () => ({ createShare: mocks.create, listShares: mocks.list, revokeShare: mocks.revoke }))
vi.mock('@/lib/preparation', () => ({ listVersions: async () => [] }))
afterEach(cleanup)
it('shows a new link once and revokes history by management ID', async () => {
  const row = { id: 'management-id', kind: 'opportunity', ref_id: 'opp', expires_at: '2026-10-01', mask_pii: true }
  mocks.list.mockResolvedValue([row])
  mocks.create.mockResolvedValue({ ...row, token: 'new-secret' })
  mocks.revoke.mockResolvedValue(undefined)
  render(<SharePanel opportunity={{ id: 'opp' } as Opportunity} onToast={() => {}} />)
  await screen.findByRole('button', { name: '撤销分享' })
  expect(screen.queryByRole('button', { name: '复制链接' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '分享整包（JD+简历）' }))
  await waitFor(() => expect((screen.getByLabelText('新分享链接') as HTMLInputElement).value).toContain('/share/new-secret'))
  fireEvent.click(screen.getByRole('button', { name: '撤销分享' }))
  await waitFor(() => expect(mocks.revoke).toHaveBeenCalledWith('management-id'))
})
