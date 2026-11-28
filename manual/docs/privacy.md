---
title: Privacy and what miAssist stores
---

# Privacy and what miAssist stores

miAssist stores very little, and nothing that identifies you.

## What is stored

- Your guidance level (beginner or expert), **only** if you use a personal link and save a
  setting. Nothing is stored for the plain `/mcp` address, and nothing is stored when you only open
  `/p/new`.
- Progress in a playbook whose app work needs it to be remembered. The start-here playbooks keep
  none: their progress is read live from the apps every time.
- Each is keyed by a one-way hash of your key, never the key itself.

## Your key is not a password

The key in your personal link selects your settings and nothing else. Every key sees the same
tools and the same apps; there is nothing a key unlocks. Anyone who has your link can see and
change your guidance level, so share it as you would a bookmark.

## What is never stored or logged

- What you ask, the arguments you pass, and what the apps answer.
- Any `Authorization` header your client sends: it is ignored.
- The request paths that carry your key: miAssist keeps no access log, and its logs name a key only
  by an eight-character fingerprint of its hash.

## The apps decide

miAssist is only ever an agent toward the suite's apps. Anything that costs money, uses the GPU(s)
available, publishes, arms or activates waits for the app's operator, in that app.

## Retention and forgetting

Settings nobody has used for 180 days are deleted automatically (the installation's operator can
change this period). Your personal page, `/p/<your-key>`, has a forget button that deletes
everything remembered for your key in one step, after a confirmation. The `miassist_reset_my_settings`
tool does the same from your assistant.
