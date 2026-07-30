from __future__ import annotations

from typing import Any

from app.db import db


def _fts_available(conn) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='telegram_message_index_fts'"
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def search_historical_messages(
    query: str,
    limit: int = 30,
    source: str | None = None,
    only_with_115: bool = False,
) -> list[dict[str, Any]]:
    """在 Telegram 历史消息缓存库（telegram_message_index）中检索。

    优先使用 FTS5 全文索引；不可用时回退到 LIKE 模糊匹配。
    返回命中的消息（含来源、消息 id、文本、上下文、日期）。
    """
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(int(limit or 30), 200))
    with db() as conn:
        if _fts_available(conn):
            return _search_fts(conn, query, limit, source, only_with_115)
        return _search_like(conn, query, limit, source, only_with_115)


def _base_where(source: str | None, only_with_115: bool) -> tuple[str, list[Any]]:
    where = []
    params: list[Any] = []
    if source:
        where.append("m.source = ?")
        params.append(source)
    if only_with_115:
        where.append("m.has_115 = 1")
    return (" WHERE " + " AND ".join(where)) if where else "", params


def _search_fts(conn, query: str, limit: int, source: str | None, only_with_115: bool) -> list[dict[str, Any]]:
    where, params = _base_where(source, only_with_115)
    # FTS5 MATCH supports quoted phrases; keep it simple and safe.
    fts_query = _fts_escape(query)
    sql = f"""
        SELECT m.source, m.message_id, m.text, m.context, m.message_date, m.has_115
        FROM telegram_message_index m
        JOIN telegram_message_index_fts f ON f.rowid = m.rowid
        WHERE telegram_message_index_fts MATCH ? {where}
        ORDER BY m.message_date DESC, m.message_id DESC
        LIMIT ?
    """
    rows = conn.execute(sql, [fts_query, *params, limit]).fetchall()
    return [_row_to_dict(row) for row in rows]


def _search_like(conn, query: str, limit: int, source: str | None, only_with_115: bool) -> list[dict[str, Any]]:
    where, params = _base_where(source, only_with_115)
    like_clause = " AND (m.text LIKE ? OR m.context LIKE ? OR m.search_blob LIKE ?)" if where else " WHERE (m.text LIKE ? OR m.context LIKE ? OR m.search_blob LIKE ?)"
    params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])
    sql = f"""
        SELECT m.source, m.message_id, m.text, m.context, m.message_date, m.has_115
        FROM telegram_message_index m
        {where}{like_clause}
        ORDER BY m.message_date DESC, m.message_id DESC
        LIMIT ?
    """
    rows = conn.execute(sql, [*params, limit]).fetchall()
    return [_row_to_dict(row) for row in rows]


def _fts_escape(query: str) -> str:
    # Quote to treat as a phrase; strip characters that break FTS syntax.
    cleaned = query.replace('"', " ").strip()
    return f'"{cleaned}"' if cleaned else query


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "source": row["source"],
        "message_id": row["message_id"],
        "text": row["text"],
        "context": row.get("context") or "",
        "message_date": row.get("message_date"),
        "has_115": bool(row.get("has_115")),
    }


def history_cache_stats() -> dict[str, Any]:
    with db() as conn:
        try:
            total = conn.execute("SELECT COUNT(*) FROM telegram_message_index").fetchone()[0]
            with_115 = conn.execute("SELECT COUNT(*) FROM telegram_message_index WHERE has_115 = 1").fetchone()[0]
            sources = conn.execute(
                "SELECT source, COUNT(*) AS c FROM telegram_message_index GROUP BY source ORDER BY c DESC LIMIT 20"
            ).fetchall()
        except Exception:
            return {"ok": False}
    return {
        "ok": True,
        "total_messages": int(total or 0),
        "messages_with_115": int(with_115 or 0),
        "sources": [{"source": row["source"], "count": int(row["c"])} for row in sources],
    }
