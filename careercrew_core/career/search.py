"""Bounded keyset search. A cursor is navigation data, never authorization."""
import base64
import hashlib
import hmac
import json

SOURCES = (
    ('opportunities', 'preparation_opportunities', ('company', 'title', 'jd'),
     'title', 'jd', 'company', 'stage'),
    ('materials', 'project_materials', ('name', 'background', 'results'),
     'name', 'background', 'NULL', 'NULL'),
    ('real_interviews', 'real_interview_records', ('company', 'title', 'overall_reflection'),
     'title', 'overall_reflection', 'company', 'NULL'),
    ('offers', 'offer_comparisons', ('company', 'title', 'notes'),
     'title', 'notes', 'company', 'NULL'),
    ('tasks', 'action_items', ('title', 'note'),
     'title', 'note', 'NULL', 'NULL'),
)


def _cursor_signature(secret: str, owner_id: str, query: str,
                      after_type: str, after_id: str) -> str:
    payload = json.dumps(
        [1, owner_id, query, after_type, after_id],
        ensure_ascii=False, separators=(',', ':'),
    ).encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def search_page(pool, owner_id: str, query: str, limit: int = 20,
                cursor: str | None = None, *, signing_secret: str):
    if not 1 <= limit <= 50:
        raise ValueError('每页数量必须为 1–50')
    after_type, after_id = '', ''
    if cursor:
        try:
            if len(cursor) > 1500:
                raise ValueError()
            data = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
            if not isinstance(data, list) or len(data) != 4 or data[0] != 1:
                raise ValueError()
            _, after_type, after_id, signature = data
            if after_type not in [s[0] for s in SOURCES] or not isinstance(after_id, str) or len(after_id) > 200:
                raise ValueError()
            expected = _cursor_signature(signing_secret, owner_id, query, after_type, after_id)
            if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
                raise ValueError()
        except Exception as exc:
            raise ValueError('搜索游标无效，请重新搜索') from exc
    parts, params = [], []
    for kind, table, fields, title, detail, company, stage in SOURCES:
        predicate = ' OR '.join(f'{field} ILIKE %s' for field in fields)
        archive = ' AND archived_at IS NULL' if kind == 'opportunities' else ''
        # Identifiers come only from the module-level SOURCES allow-list; all user data is bound.
        parts.append(f"SELECT '{kind}' AS kind, id, {title} AS title, "  # noqa: S608
                     f"substr({detail},1,240) AS summary, {company} AS company, "
                     f"{detail} AS detail, {stage} AS stage FROM {table} "
                     f"WHERE owner_id=%s AND ({predicate}){archive}")
        params.extend([owner_id, *([f'%{query}%'] * len(fields))])
    sql = 'SELECT * FROM (' + ' UNION ALL '.join(parts) + ') AS results WHERE (kind > %s OR (kind = %s AND id > %s)) ORDER BY kind, id LIMIT %s'  # noqa: S608
    params.extend([after_type, after_type, after_id, limit + 1])
    with pool.connection() as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    page_rows = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        tail = page_rows[-1]
        signature = _cursor_signature(
            signing_secret, owner_id, query, tail['kind'], tail['id'],
        )
        next_cursor = base64.urlsafe_b64encode(json.dumps(
            [1, tail['kind'], tail['id'], signature], separators=(',', ':'),
        ).encode()).decode().rstrip('=')
    page = [{key: row[key] for key in ('kind', 'id', 'title', 'summary')} for row in page_rows]
    # Keep the exact legacy category row shapes during the UI/API transition.
    grouped = {source[0]: [] for source in SOURCES}
    for row in page_rows:
        if row['kind'] == 'opportunities':
            item = {key: row[key] for key in ('id', 'company', 'title', 'stage')}
            item['jd'] = row['detail']
        elif row['kind'] == 'materials':
            item = {'id': row['id'], 'name': row['title'], 'background': row['detail']}
        elif row['kind'] == 'real_interviews':
            item = {key: row[key] for key in ('id', 'company', 'title')}
            item['overall_reflection'] = row['detail']
        elif row['kind'] == 'offers':
            item = {key: row[key] for key in ('id', 'company', 'title')}
            item['notes'] = row['detail']
        else:
            item = {'id': row['id'], 'title': row['title'], 'note': row['detail']}
        grouped[row['kind']].append(item)
    return {'items': page, 'next_cursor': next_cursor, **grouped}
