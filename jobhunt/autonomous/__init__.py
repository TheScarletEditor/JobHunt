"""Autonomous Apply.

Saved searches discover jobs from ATS company boards or third-party APIs,
score them against a chosen resume, queue the matches above a threshold,
and (optionally) auto-fill + auto-submit applications for trusted ATSes.

Module layout:
  searches.py  — DB-backed CRUD for saved_searches rows + source criteria
  sources.py   — pluggable backends (Greenhouse/Lever/Ashby/Workable, Adzuna)
  scanner.py   — runs one saved search end-to-end, dedupes, queues
  scorer.py    — AI fit-scoring worker
  scheduler.py — background timer that runs saved searches on their cadence
  fire.py      — whitelist + daily-cap gates for auto-submit
  queue.py     — read/action helpers for the job_queue table
"""
