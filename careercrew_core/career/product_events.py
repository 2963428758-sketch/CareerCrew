"""Content-free, owner-scoped product events for a voluntary user pilot."""
import logging
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

EventName = Literal['opportunity_saved', 'application_kit_generated', 'material_copied', 'material_saved', 'task_completed', 'share_panel_opened', 'share_created', 'share_accessed']
Source = Literal['preparation', 'career', 'public_share', 'api']


class ProductEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event: EventName
    event_id: UUID
    source: Source = 'api'
    object_id: UUID | None = None


def record_event(pool, owner_id, payload: ProductEvent):
    with pool.connection() as conn:
        conn.execute('INSERT INTO career_product_events (id, owner_id, event, source, object_id) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (owner_id,id) DO NOTHING',
                     (str(payload.event_id), owner_id, payload.event, payload.source, str(payload.object_id) if payload.object_id else None))


def safe_event(pool, owner_id, event: EventName, source: Source = 'api'):
    try:
        record_event(pool, owner_id, ProductEvent(event=event, event_id=uuid4(), source=source))
    except Exception:
        logging.getLogger(__name__).warning('product_event_write_failed event=%s', event)


def event_funnel(pool, owner_id):
    with pool.connection() as conn:
        rows = conn.execute('SELECT event, COUNT(*) AS n FROM career_product_events WHERE owner_id=%s GROUP BY event', (owner_id,)).fetchall()
    return {'counts': {r['event']: r['n'] for r in rows}, 'note': '操作次数统计，同一人可能重复操作；不代表因果转化率。'}
