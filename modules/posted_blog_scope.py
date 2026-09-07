"""Preserve per-blog product exclusion state while legacy SQL uses a current view."""

import sqlite3
from typing import Final

POSTED_FIELDS: Final = (
    ("already_posted", "INTEGER", 0),
    ("already_posted_review", "INTEGER", 0),
    ("already_posted_auto_ignored", "INTEGER", 0),
    ("already_posted_method", "TEXT", ""),
    ("already_posted_title", "TEXT", ""),
    ("already_posted_url", "TEXT", ""),
    ("already_posted_at", "TEXT", ""),
    ("already_posted_match_score", "REAL", 0),
)


def switch_scope(con: sqlite3.Connection, blog_id: str) -> None:
    """Archive the visible scope before restoring another; unknown history stays archived."""
    definitions = ",".join(f"{name} {kind}" for name, kind, _ in POSTED_FIELDS)
    columns = ",".join(name for name, _, _ in POSTED_FIELDS)
    con.execute(
        "CREATE TABLE IF NOT EXISTS posted_blog_state ("
        f"blog_id TEXT NOT NULL,product_id INTEGER NOT NULL,{definitions},"
        "PRIMARY KEY(blog_id,product_id))"
    )
    con.execute("CREATE TABLE IF NOT EXISTS posted_blog_view (singleton INTEGER PRIMARY KEY CHECK(singleton=1),blog_id TEXT NOT NULL)")
    previous = con.execute("SELECT blog_id FROM posted_blog_view WHERE singleton=1").fetchone()
    old_scope = str(previous[0]) if previous else ""
    if previous and old_scope == blog_id:
        return
    if old_scope or previous is None:
        con.execute(
            f"INSERT OR REPLACE INTO posted_blog_state(blog_id,product_id,{columns}) "
            f"SELECT ?,id,{columns} FROM products", (old_scope,),
        )
    for name, _, default in POSTED_FIELDS:
        if blog_id:
            con.execute(
                f"UPDATE products SET {name}=COALESCE((SELECT {name} FROM posted_blog_state "
                "WHERE product_id=products.id AND blog_id=?),?)", (blog_id, default),
            )
        else:
            con.execute(f"UPDATE products SET {name}=?", (default,))
    con.execute("INSERT OR REPLACE INTO posted_blog_view VALUES(1,?)", (blog_id,))
