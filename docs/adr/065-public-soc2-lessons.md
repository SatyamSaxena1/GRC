# ADR-065: Free public lessons, starting with "SOC 2 in plain words"

**Status:** Accepted
**Date:** 2026-11-12
**Deciders:** Platform owner

## Context
Step 2 of the course plan agreed in ADR-064: our own learning content about compliance, free to read, as a way for
buyers to find us. The owner asked to start with SOC 2.

## Decision
- **A public page at `/learn/soc-2`**, no sign-in, linked from the sign-in page. Five lessons to start: what SOC 2 is,
  Type 1 and Type 2, scope and controls, evidence, and the first 90 days.
- **The lessons live in the frontend code** (`frontend/src/lib/soc2Lessons.ts`), not the database. They are ours and
  the same for everyone, so a change goes through a pull request like any other, and no tenant table is involved.
- **Practice situations are checked in the browser and nothing is recorded.** They grade nothing for anyone and are
  not the Training result of ADR-064. The page makes no calls to the server.
- **Written in our own words, drafted with AI help.** The page shows "Draft: these lessons are still being reviewed"
  until the owner has read them and `REVIEWED` is set to true.

## Consequences
- Not done: the other SOC 2 lessons (to reach ten), other frameworks, search-engine titles and descriptions for each
  lesson, and sign-up tracking from the page.
