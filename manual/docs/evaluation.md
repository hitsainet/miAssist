---
title: How miAssist is evaluated
---

# How miAssist is evaluated

Every release of miAssist is measured against the way people used the suite before it: the apps'
own tool servers, connected together in the same client. The question each run answers is plain:
**can a newcomer, writing an ordinary request, reach the result they asked for?**

## What a run is

A run starts from a goal written the way a newcomer would write it, with no tool names, no app
names and no steps. Three goals are used: setting up a check that spots refund requests and
watching a served model with it; building, checking and publishing a small dataset of support
messages; and making a served model sound warmer. The data is synthetic or public, made for the
evaluation; no operator data is used.

A run succeeds only when the apps show the result happened (a dataset version built, a check
trained and evaluated, a change switched on by the operator) **and** the assistant's last message
states the outcome with figures the apps really returned. Approvals and switching things on are
always the operator's; the assistant never decides them.

## The three tiers

- **Tier 1a**, on every change: a scripted client follows each playbook against recorded app
  answers. It runs in continuous integration and uses no model.
- **Tier 1b**, by hand: real clients (Claude Code and Open WebUI) with a model, against the same
  recordings, ten runs per cell. It never runs in continuous integration.
- **Tier 2**, once per release, by hand: the same clients against the live apps, with the operator
  approving each step.

## How to read a report

Each cell is one playbook with one client. It reads **PASS**, **FAIL**, **NOT MEASURED** (fewer
than ten valid runs) or **NOT RUN** (no attempt), and only the first ten valid runs count, so
re-running until a pass shows up does not change a verdict. The bar is nine successes in ten, at
least half the calls the baseline needed, and the first useful result within ten minutes of active
time in nine runs of ten. A release reads **BAR MET** only when every required cell passes, every
tier-2 run succeeded and every manual check passed. Figures are published here after the
operator reviews each report; no transcript or app answer is ever published.
