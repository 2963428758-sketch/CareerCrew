"""@ 引用（mentions）校验与服务端资源解析（T3.4 §15.2）。

Mention 的 ``id`` 来自客户端，不可信任：服务端必须再次校验 ownership /
visibility 后才可把资源作为本轮强制上下文（或记录进 turn metadata）：

- knowledge_document → 复用 vector store 查询（owner/visibility 过滤）：
  private → resource.owner_user_id == current_user.id；public → visibility == public。
- resume → 本人简历库条目（data/parsed/resumes/{user_id}/{resume_id}）。

校验失败抛出 :class:`MentionRejected`；路由层映射为 422/404（实现者定，语义=拒绝）。

本模块为纯函数：``knowledge_docs`` / ``resume_items`` 由调用方按当前用户预过滤为
可见集合后传入（对照 runtime.list_context_resources / resolve_mentions 接缝），
不反向依赖渲染层，可独立单测。
"""
from __future__ import annotations

from dataclasses import dataclass

# 可引用的资源类型（§15；不含 @Agent）
RESOURCE_TYPE_KNOWLEDGE = "knowledge_document"
RESOURCE_TYPE_RESUME = "resume"


class MentionRejected(Exception):
    """mention 校验失败：资源不存在 / 越权 / 伪造 visibility。路由层语义=拒绝。"""


@dataclass(frozen=True)
class ResolvedMention:
    """校验通过后的 mention 解析结果（含展示名与类型）。"""

    type: str
    id: str
    name: str = ""
    visibility: str = "private"

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "visibility": self.visibility,
        }


def _lookup_knowledge_doc(user_id: str, doc_id: str, docs: list[dict]) -> ResolvedMention | None:
    """在已过滤的知识文档列表里命中指定 doc；校验 owner/visibility。"""
    for d in docs:
        if str(d.get("doc") or "") != doc_id:
            continue
        owner = str(d.get("owner_user_id") or "")
        visibility = str(d.get("visibility") or "private")
        # private 必须本人；public 对任何人可见。混合库（本人 private 已在上游过滤）。
        if visibility == "public" or owner == user_id:
            return ResolvedMention(
                type=RESOURCE_TYPE_KNOWLEDGE,
                id=doc_id,
                name=str(d.get("doc") or doc_id),
                visibility=visibility,
            )
        # 命中同 id 但既非 public 也非本人 → 越权
        return None
    return None


def resolve_mentions(
    user_id: str,
    mentions: list[dict],
    *,
    knowledge_docs: list[dict],
    resume_items: list[dict],
) -> list[ResolvedMention]:
    """逐条校验 mentions，返回 resolved 列表；任一不合法抛 :class:`MentionRejected`。

    ``knowledge_docs`` / ``resume_items`` 由调用方按当前用户预过滤为可见集合
    （见 :func:`list_context_resources`），此处仅做最终 ownership/visibility 判定，
    不信任任何来自 ``mentions`` 的 id/type。
    """
    resolved: list[ResolvedMention] = []
    resume_by_id = {
        str(r.get("resume_id") or ""): r
        for r in resume_items
        if str(r.get("user_id") or user_id) == user_id  # resume 本人所有（§15.2）
    }
    for m in mentions:
        mtype = str(m.get("type") or "")
        mid = str(m.get("id") or "")
        if not mid:
            raise MentionRejected("mention 缺少资源 id")
        if mtype == RESOURCE_TYPE_KNOWLEDGE:
            hit = _lookup_knowledge_doc(user_id, mid, knowledge_docs)
            if hit is None:
                raise MentionRejected(f"知识文档不存在或不可引用：{mid}")
            resolved.append(hit)
        elif mtype == RESOURCE_TYPE_RESUME:
            item = resume_by_id.get(mid)
            if item is None:
                raise MentionRejected(f"简历不存在或不可引用：{mid}")
            resolved.append(ResolvedMention(
                type=RESOURCE_TYPE_RESUME,
                id=mid,
                name=str(item.get("filename") or mid),
                visibility="private",
            ))
        else:
            raise MentionRejected(f"不支持的引用类型（仅支持知识文档与简历）：{mtype}")
    return resolved
