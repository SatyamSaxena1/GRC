# ADR-064: Training courses with lessons and graded scenario questions

**Status:** Accepted
**Date:** 2026-11-12
**Deciders:** Platform owner

## Context
The owner asked to "start making a full course like Coursera". On 2026-11-12 the owner agreed the scope in writing:

1. **First: courses for a customer's own staff**, built on the Training module (ADR-063): several lessons, scenario
   questions in plain text, progress, and a result with a pass, partial or fail mark.
2. **Then: our own public learning content** (for example "SOC 2 in 10 lessons"), free to read, to attract buyers.
3. **Later, asked for by the owner, not built here:** a merit record that tells an employer how well a person uses the
   tool, a leaderboard of auditors and audit firms, and a **final exam** last: a fixed, scripted practice screen (a
   pretend workspace, a side panel of policy documents to edit, drag-and-drop steps that attach nothing) where the
   person's steps are graded against a set answer, with an "explain the answer" mode that plays the steps with notes.

This ADR covers only the first slice of (1).

## Decision
- **A course can have lessons.** `training_courses.lessons` holds an ordered list of lessons; each has a title, text and
  zero or more scenario questions (a situation, two to six choices, the right choice and why it is right). The lessons
  are part of the course text: changing them makes a new version, exactly as changing the text does in ADR-063.
- **Fixed rules grade the answers, never a model.** The right choice is stored with the question; the server compares.
  The right choice and the reason are sent to a person only after they answer, then shown under each question.
- **Every try is kept** in `training_attempts` (insert-only, row level security): person, course, version, lesson, the
  choices made, how many were right, when. Each try is an audit event (`TRAINING_ANSWERED`). Tries on an old version do
  not count.
- **Retries are allowed without limit, and a person's best try per lesson counts.** The course result is the share of
  questions right across those best tries, once every lesson has been tried: **PASS at 80% or more, PARTIAL at 50% or
  more, FAIL below.** Before that it is NOT_STARTED or IN_PROGRESS. The marks are fixed for now.
- **An organisation admin sees every person's progress and result;** a member sees only their own.
- **The yearly "I have read and understood" statement from ADR-063 is unchanged and separate.** The result does not
  replace it and does not attest any control.
- **One template course, "Using GRC: the basics",** teaches the product itself (evidence, verdicts, statements,
  policies, auditors). It was drafted with AI help in our own words and needs the owner's review before customers rely
  on it; an admin can still edit any course.

## What a PASS proves, and what it does not
- **It proves** that, on that day, the person picked the set answer to at least 80% of the questions in that version
  of the course, on their best try at each lesson.
- **It does not prove** that the person is competent, that they did not look the answers up, or that they remembered
  them later. Unlimited retries with the answers explained mean anyone who keeps going will pass. That is intended:
  the goal is that everyone ends up knowing the right answer. A PARTIAL or FAIL shows who stopped early.
- It is not evidence for any control and changes no verdict. Any later merit record or leaderboard must say the same
  thing in its own words, and must not rank people or firms on this result alone.

## Consequences
- Not done in this slice: writing lessons and questions in the page (an admin can add the template, and the API takes
  lessons), certificates, the merit record, the leaderboard, public content, video, and the scripted final exam.
- The owner raised the leaderboard of auditors. Before it is built, it needs its own decision covering consent,
  what is shown publicly, and how a score is earned, because a public ranking is a claim about named people and firms.
