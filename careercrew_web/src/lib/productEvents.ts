import { apiFetch } from './auth'

export async function trackProductEvent(
  event: 'share_panel_opened' | 'material_copied' | 'material_saved',
  source: 'preparation' | 'career',
): Promise<void> {
  try {
    await apiFetch('/api/career/events', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event, source, event_id: crypto.randomUUID() }),
    })
  } catch { /* Optional analytics must never block the user's completed action. */ }
}
