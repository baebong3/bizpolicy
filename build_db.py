#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bizpolicy 적재기: biz_news.json → news.db (누적·멱등)
스키마는 리포트 생성기(monthly_brief/feature_report)와 호환.

  python build_db.py
"""
import json, os, sqlite3
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "news.db")
SRC = os.path.join(HERE, "biz_news.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  scope TEXT NOT NULL, id TEXT NOT NULL, date TEXT, title TEXT, url TEXT,
  source TEXT, sentiment TEXT, code TEXT, field TEXT, dept TEXT, sido TEXT,
  description TEXT, is_new INTEGER, first_seen TEXT, PRIMARY KEY (scope, id));
CREATE TABLE IF NOT EXISTS article_topics (
  scope TEXT NOT NULL, id TEXT NOT NULL, topic TEXT NOT NULL,
  PRIMARY KEY (scope, id, topic));
CREATE TABLE IF NOT EXISTS new_policies (date TEXT, title TEXT, dept TEXT, field TEXT, summary TEXT, PRIMARY KEY (date, title));
CREATE TABLE IF NOT EXISTS watchlist (date TEXT, code TEXT, name TEXT, dept TEXT, field TEXT, neg INTEGER, PRIMARY KEY (date, code));
CREATE INDEX IF NOT EXISTS ix_a_date ON articles(date);
CREATE INDEX IF NOT EXISTS ix_a_scope ON articles(scope, date);
"""


def main():
    if not os.path.exists(SRC):
        raise SystemExit("biz_news.json이 없습니다 — collect_biz_news.py를 먼저 실행하세요")
    doc = json.load(open(SRC, encoding="utf-8"))
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    today = datetime.now().strftime("%Y-%m-%d")
    rows, topics = [], []
    for it in doc.get("items", []):
        sc = it.get("scope") or ("지자체" if it.get("sido") else "중앙")
        rows.append((sc, it["id"], it.get("date"), it.get("title"), it.get("url"),
                     it.get("source"), it.get("sentiment"), None, it.get("field"),
                     it.get("dept"), it.get("sido"), (it.get("description") or "")[:300] or None,
                     0, today))
        for tp in it.get("topics") or []:
            topics.append((sc, it["id"], tp))
    before = con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    con.executemany("INSERT OR IGNORE INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT OR IGNORE INTO article_topics VALUES (?,?,?)", topics)
    con.executemany("UPDATE articles SET description=? WHERE scope=? AND id=? AND (description IS NULL OR description='')",
                    [(r[11], r[0], r[1]) for r in rows if r[11]])
    con.commit()
    after = con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    span = con.execute("SELECT MIN(date), MAX(date) FROM articles").fetchone()
    print(f"적재: 원본 {len(rows):,}건 → 신규 {after-before:,}건 (누적 {after:,}건, {span[0]}~{span[1]})")


if __name__ == "__main__":
    main()
