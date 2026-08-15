plan: docs/superpowers/plans/2026-08-15-multiuser-auth-knowledge.md

Task A1: complete (commit 29db20f, 20/20 config tests)
Task A2: complete (commit HEAD, 8/8 unit + 1/1 postgres integration)

Task A3: complete (11/11 unit)

Task A4: complete (9/9 auth api)

Task A5: complete (11/11)

Task A6: complete (4/4 unit + 1/1 pg integration)

Task B1: complete (23/23 vector store tests)

Task B2+B3: complete (27 knowledge api + visibility matrix green)

Task B4: complete (16/16 migration tests)

Task B4 live: careercrew_mm 211 点迁移完成（changed=211→rerun 0/211 skip），episodic 未动；langchain_v1_tools 4 点迁移前已被删除（原始文件仍在）

Task D1: complete (fetch_kb/ingest reworked, data/knowledge archived, OPS_BACKUP.md added)

Task D2: complete (backend 437 passed incl. integration; frontend 14/14 + lint 0 + build ok; live PG auth smoke ok)

FIX login: integration tests had wiped prod auth_accounts; restored u_001/liyou from sqlite backup, added disposable-db guard + careercrew_test

