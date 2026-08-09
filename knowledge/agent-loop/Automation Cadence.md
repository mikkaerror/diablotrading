---
type: agent-loop-operations
updated: "2026-08-09"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - agent-loop
  - automation
  - scheduling
  - observability
---

# Automation Cadence

Links: [[Loop Optimization Principles]] · [[Authority Boundary]] · [[Artifact Lifecycle]]

## Belief

Scheduler visibility must separate deployment drift, intentionally custom
cadence, and same-minute timing overlap. None of those observations proves
duplicate work or authorizes a scheduler change.

## Contract

`./inferno schedule` reads configured launchd and Codex automation metadata.
It compares the daily loop's fixed clock times with its installer defaults and
reports exact fixed-time overlaps by day. It excludes interval jobs from clock
collision claims because an interval does not promise a wall-clock minute.

The diagnostic is strictly read-only. It never starts, reinstalls, reschedules,
or disables work; it cannot alter broker authority, paper tickets, promotion
gates, risk constants, or the eligible universe.

## Evidence

On 2026-08-09, the installed daily digest used the deliberately preserved
07:30/17:10 weekday cadence rather than the installer defaults of 06:30/16:30.
The weekday 07:30 Morning Conviction Brief shares a fixed minute with the daily
digest. The jobs have different prompts and outputs, so the overlap is a
review-only resource/duplication question, not duplicate-work evidence.

## Falsifier

This belief is false if schedule output labels a custom cadence as deployment
drift, treats an interval as a fixed-clock collision, claims an overlap proves
duplicate work, or changes a schedule without an explicit human operator
action.
