---
type: agent-loop-operations
updated: "2026-07-14"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - agent-loop
  - email
  - deduplication
  - safety
---

# Approval Inbox Scan Discipline

Links: [[Loop Optimization Principles]] · [[Authority Boundary]] · [[Storage Hygiene]]

## Durable rule

An approval-reply poll must search for the narrowest stable message signature,
reject unauthorized senders, and bound non-action dedupe state. Records that
actually changed the paper approval queue remain durable. Inbox scanning never
grants broker or live-trading authority.

## Evidence

On 2026-07-14 the inbox state held 31,510 UIDs occupying 3.5 MB. Of those,
31,083 were `sender-not-allowed`, and the latest poll spent all 24 checks on
unrelated senders with zero applied commands. The configured query was the
broad default `UNSEEN`.

The default query now requires `[Inferno Approval]` in an unread subject, and
transient dedupe history is capped at 5,000 records while every `applied`
record is preserved.

## Falsifier

This rule is failing if unrelated mail again dominates checked messages, the
transient UID set grows beyond its cap after a successful state save, or any
applied approval record is removed by compaction.

This policy cannot approve, reject, close, or promote a ticket, alter the
eligible universe or risk constants, or enable broker submission.
