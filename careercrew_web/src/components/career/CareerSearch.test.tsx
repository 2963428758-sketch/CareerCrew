// @vitest-environment jsdom
import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { CareerSearch } from './CareerSearch'
const search = vi.hoisted(() => vi.fn())
vi.mock('@/lib/career', () => ({ globalSearch: search }))
afterEach(cleanup)
it('appends the next page for the submitted query', async () => {
  search.mockResolvedValueOnce({ items: [{ id: 'a', kind: 'opportunities', title: '岗位一', summary: '' }], next_cursor: 'cursor-a' })
    .mockResolvedValueOnce({ items: [{ id: 'b', kind: 'tasks', title: '任务二', summary: '' }], next_cursor: null })
  render(<MemoryRouter><CareerSearch onToast={() => {}} /></MemoryRouter>)
  fireEvent.change(screen.getByPlaceholderText('搜索关键词'), { target: { value: '岗位' } })
  fireEvent.click(screen.getByRole('button', { name: '搜索' }))
  await screen.findByText('岗位一')
  fireEvent.click(screen.getByRole('button', { name: '加载更多' }))
  await screen.findByText('任务二')
  expect(screen.getByText('岗位一')).toBeTruthy()
  expect(search).toHaveBeenLastCalledWith('岗位', 'cursor-a')
})
