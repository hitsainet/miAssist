---
slug: /
title: Quick start
---

# Quick start

miAssist is one MCP server that guides you through the miStudio suite. It works with any
combination of the suite's apps: it offers only what your installation has, and it never asks you
to install something else.

## 1. Connect

Add miAssist to your MCP client as a remote server. The two address forms, where your personal key
goes, and the steps for each client are on the [Connect](./connect.md) page. No token is needed.

## 2. Ask the guide

Ask your assistant to call `miassist_guide`. It lists the apps installed here, whether each one is
answering, and the playbooks on offer: short, guided paths through a task, one step at a time.

## 3. Take a start-here playbook

Each installed app has a start-here playbook (`start-<app>`): a first look at what the app holds,
one of its key words, and where to go next. Ask for it by name, for example "take the start-here
playbook for this app", and your assistant follows its steps. Call `miassist_status` with the
playbook's id at any time to see the steps done and the next one.

## Reading a result

Every result has the same shape: the data, then suggested next steps, each with a reason. At the
beginner level each result also carries a short explanation; switch to expert with
`miassist_set_guidance` on a personal link. When an app must ask its operator first, the result
says where the request waits; you cannot approve it yourself. Words you may not know link to the
[Glossary](./glossary.md).
