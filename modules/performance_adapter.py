# -*- coding: utf-8 -*-
from pathlib import Path
import sqlite3, json, math, statistics, time, re
from .common import DB, log

def ensure_tables():
    con=sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS post_performance(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER,
      post_date TEXT,
      category TEXT,
      title TEXT,
      views INTEGER DEFAULT 0,
      likes INTEGER DEFAULT 0,
      comments INTEGER DEFAULT 0,
      inbound_search INTEGER DEFAULT 0,
      outbound_clicks INTEGER DEFAULT 0,
      dwell_seconds REAL DEFAULT 0,
      source TEXT DEFAULT 'manual',
      captured_at TEXT
    );
    CREATE TABLE IF NOT EXISTS category_strategy(
      category TEXT PRIMARY KEY,
      recent_posts INTEGER DEFAULT 0,
      avg_views REAL DEFAULT 0,
      avg_inbound REAL DEFAULT 0,
      avg_engagement REAL DEFAULT 0,
      score REAL DEFAULT 0,
      next_weight REAL DEFAULT 1.0,
      updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS seo_experiments(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER,
      experiment_type TEXT,
      variant TEXT,
      result_metric REAL,
      note TEXT,
      created_at TEXT
    );
    """)
    con.commit();con.close()

def add_performance(product_id, category, title, views=0, likes=0, comments=0,
                    inbound_search=0, outbound_clicks=0, dwell_seconds=0, post_date=None, source="manual"):
    ensure_tables()
    con=sqlite3.connect(DB)
    con.execute("""INSERT INTO post_performance(product_id,post_date,category,title,views,likes,comments,
                   inbound_search,outbound_clicks,dwell_seconds,source,captured_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                (product_id,post_date or time.strftime("%Y-%m-%d"),category,title,views,likes,comments,
                 inbound_search,outbound_clicks,dwell_seconds,source))
    con.commit();con.close()

def _norm(v, vals):
    if not vals:return 0
    lo=min(vals);hi=max(vals)
    return 0.5 if hi==lo else (v-lo)/(hi-lo)

def recompute_strategy(lookback=30):
    """Use the most recent N published-performance rows and reward real search inflow, not posting volume."""
    ensure_tables()
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    rows=con.execute("""SELECT * FROM post_performance ORDER BY COALESCE(post_date,captured_at) DESC,id DESC LIMIT ?""",(lookback,)).fetchall()
    cats={}
    for r in rows:
        c=r["category"] or "미분류"
        g=cats.setdefault(c,{"n":0,"views":[],"inbound":[],"engagement":[],"clicks":[],"dwell":[]})
        g["n"]+=1;g["views"].append(r["views"] or 0);g["inbound"].append(r["inbound_search"] or 0)
        eng=(r["likes"] or 0)*1.0+(r["comments"] or 0)*2.0
        g["engagement"].append(eng);g["clicks"].append(r["outbound_clicks"] or 0);g["dwell"].append(r["dwell_seconds"] or 0)
    if not cats:
        con.close();return {}
    summary={}
    view_avgs={c:sum(g["views"])/g["n"] for c,g in cats.items()}
    in_avgs={c:sum(g["inbound"])/g["n"] for c,g in cats.items()}
    en_avgs={c:sum(g["engagement"])/g["n"] for c,g in cats.items()}
    cl_avgs={c:sum(g["clicks"])/g["n"] for c,g in cats.items()}
    dw_avgs={c:sum(g["dwell"])/g["n"] for c,g in cats.items()}
    for c,g in cats.items():
        # Search traffic is the strongest signal. Views alone are discounted.
        score=(0.45*_norm(in_avgs[c],list(in_avgs.values()))+
               0.20*_norm(view_avgs[c],list(view_avgs.values()))+
               0.15*_norm(en_avgs[c],list(en_avgs.values()))+
               0.10*_norm(cl_avgs[c],list(cl_avgs.values()))+
               0.10*_norm(dw_avgs[c],list(dw_avgs.values())))
        # Bayesian-ish shrinkage: categories with only one post cannot dominate immediately.
        confidence=min(1.0,g["n"]/5.0)
        adj=0.5+(score-0.5)*confidence
        # Keep exploration: never starve a category entirely.
        weight=max(0.55,min(1.75,0.75+adj))
        summary[c]={"recent_posts":g["n"],"avg_views":view_avgs[c],"avg_inbound":in_avgs[c],
                    "avg_engagement":en_avgs[c],"score":adj,"next_weight":weight}
        con.execute("""INSERT INTO category_strategy(category,recent_posts,avg_views,avg_inbound,avg_engagement,score,next_weight,updated_at)
                       VALUES(?,?,?,?,?,?,?,datetime('now','localtime'))
                       ON CONFLICT(category) DO UPDATE SET recent_posts=excluded.recent_posts,avg_views=excluded.avg_views,
                       avg_inbound=excluded.avg_inbound,avg_engagement=excluded.avg_engagement,score=excluded.score,
                       next_weight=excluded.next_weight,updated_at=excluded.updated_at""",
                    (c,g["n"],view_avgs[c],in_avgs[c],en_avgs[c],adj,weight))
    con.commit();con.close()
    return summary

def get_weights(default_categories):
    ensure_tables();recompute_strategy()
    con=sqlite3.connect(DB);rows=con.execute("SELECT category,next_weight FROM category_strategy").fetchall();con.close()
    m={c:w for c,w in rows}
    return {c:float(m.get(c,1.0)) for c in default_categories}
