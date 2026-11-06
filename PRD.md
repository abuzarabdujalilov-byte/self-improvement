# Lucid — Product Requirements Document

| | |
| --- | --- |
| **Product** | Lucid |
| **Status** | Draft for review. Development has not started. |
| **Date** | 6 November 2026 |
| **Audience for this document** | Product review before any build |

This document records the decisions from the discovery interview. It does not authorise development. Building starts only after you approve it, including the three open points in section 12.

---

## 1. Summary

Lucid is a practice site for school students aged 16 and over who want to develop their thinking. A student signs in with Google, works through chess puzzles and logic problems, and the site chooses the next exercise from what they got right or wrong. They can see a separate score for chess and a separate score for logic.

An AI assistant is part of the practice, not a separate product. The student asks their own questions and gets answers for that conversation. The assistant uses Google Gemini. Each student supplies their own Gemini API key. The student chooses among Gemini 3.8 Flash, Gemini 3.6 Flash, and Gemini 3.5 Flash-Lite.

The first version is a coherent practice loop: exercise, result, next exercise, score, and a free conversation when the student needs help. It is not a chess club, a school portal, or a collection of mini-games.

---

## 2. Who it is for

**Primary user:** a school student, aged 16 or over, who is curious about developing their thinking and can practise on their own.

- The student joins alone. A teacher, a class, or a school account is not required.
- The student signs in with a Google account.
- The site states that it is for ages 16 and over, and the student confirms that age before using practice. Google sign-in does not provide a reliable proof of age, so the requirement is an explicit confirmation plus a clear age statement, not a claim that the site can verify a birthday.
- University students, students under 16, and teachers are not users of this version.

---

## 3. Purpose

A student comes to Lucid to practise. The visit is successful when they complete real exercises, understand a result when they ask, see chess and logic scores change, and leave with a next exercise already chosen.

The assistant is there when they have a question. It explains a chess answer, helps them think through a longer logic problem, and can also discuss science, philosophy, and other subjects. Those conversations do not have their own section of the site.

---

## 4. First version

### 4.1 Chess

- Chess practice is puzzles only.
- There is no board for playing a full game against a computer or another person.
- There are no clubs, tournaments, ratings ladders, opening courses, or public player profiles.
- A puzzle has a position and a solution the site can check without the AI.
- After an attempt, the student sees whether the answer was right.
- The student can ask the assistant about that puzzle in their own words. The assistant receives the position and the result so the explanation matches the exercise they just did.
- The next chess puzzle is chosen from the student’s recent right and wrong answers.

### 4.2 Logic

Logic practice has two kinds of exercise.

1. **Short challenges** with a clear right answer, such as a pattern, a deduction, or a number problem. The site checks the answer. The student can ask the assistant why.
2. **Longer problems** that can be approached in more than one reasonable way. The student writes their reasoning. The assistant helps them think it through. It does not pretend there is one official sentence that scores as correct.

### 4.3 Progress and the next exercise

- The dashboard shows two scores: one for chess and one for logic.
- It does not use levels, ranks, or streaks as the measure of progress.
- The site chooses the next exercise. The student does not have to build their own plan.
- A correct clear-answer attempt leads toward a harder exercise of that type. A miss leads toward an easier one.
- The dashboard shows the next chess exercise and the next logic exercise.

### 4.4 Assistant

- The student can type any question or instruction.
- Replies are generated for that conversation. The product has no menu of allowed questions and no stock answers.
- The conversation keeps earlier turns, so a follow-up can refer to what was just said.
- When the student asks from inside an exercise, that exercise is included as context.
- The assistant can discuss science, philosophy, and other subjects. There is no lessons library, course list, or discussion community for those subjects.
- The assistant does not mark clear-answer chess or logic items. The site’s own checker does that.
- The student chooses the model for their messages:
  - Gemini 3.8 Flash, model ID `gemini-3.8-flash`
  - Gemini 3.6 Flash, model ID `gemini-3.6-flash` (default)
  - Gemini 3.5 Flash-Lite, model ID `gemini-3.5-flash-lite`
- `gemini-3.5-flash` is deprecated and must not be offered. Google routes that old ID to Gemini 3.6 Flash.
- These IDs were checked against Google’s Gemini API models, deprecations, and pricing pages on 6 November 2026. They are checked again before implementation. If one has been retired, it is replaced with the documented successor and the label is updated. An invented ID is not used.

### 4.5 The student’s key

- Every student uses their own Google AI Studio API key.
- Lucid has no shared Gemini key for students.
- The student can get a key from [Google AI Studio](https://aistudio.google.com/app/apikey). The product includes a short guide: sign in, open the API keys page, create or copy a key, paste it into Lucid, and choose a model.
- Usage and any free allowance stay on that student’s Google account. The guide says so in plain language.
- The key is sent only to the Lucid server over HTTPS. The browser does not call Gemini with the key.
- The server stores the key encrypted, tied to that Google account, and shows only the last four characters after it is saved.
- The student can replace or remove the key. Removing it deletes the stored copy.
- The key is never written into the page source, logs, or analytics.
- Chat is blocked until that student’s key has been accepted by a short Gemini check.
- Invalid keys, quota limits, unavailable models, blocked prompts, and network failures are shown in ordinary language. The student’s draft stays in the box so they can retry.

---

## 5. Not in this version

You asked not to plan extra products yet. The items below are excluded, not scheduled.

- Playing full chess games
- Clubs, discussions, leaderboards, ratings, and competitions
- Opening courses and public profiles
- A teacher or class view
- Memory, focus, observation, and mental-arithmetic training
- A section of lessons or articles for science, philosophy, or other subjects
- Students under 16
- A separate path for university students
- Levels, ranks, and streaks

The implementation should keep the assistant, the exercise checker, and the pages separate, so a later addition does not require a rewrite. That is a construction rule, not a promise to build those additions.

---

## 6. Design

The interface is dark, minimal, and futuristic, without decoration that gets in the way.

- Dark background, limited colour, and type that is easy to read for a long practice session.
- The same spacing, type, and components on every page.
- Navigation that makes Practice, Progress, and the Assistant obvious.
- The dashboard shows the two scores and the next exercise. It should feel like a working desk, not a game arcade and not a school homework portal.
- Puzzles and problems are the main activity. Visuals support the position, the question, and the result.
- The layout works on a desktop, a tablet, and a phone. On a phone, the current exercise and the way to answer it stay reachable without hunting.

---

## 7. Main path

1. The student opens Lucid, reads that it is for ages 16 and over, and confirms their age.
2. They sign in with Google.
3. They paste a Gemini key, choose a model, and the site checks the key.
4. The dashboard shows the chess score, the logic score, and the next exercise of each kind.
5. They solve a chess puzzle or a logic exercise.
6. A clear-answer item is marked by the site. A longer logic problem receives an assistant response to their reasoning.
7. The matching score updates, and the next exercise is chosen.
8. At any point they can ask the assistant their own question, including a question about the exercise on screen.

---

## 8. Content

### Chess

Chess puzzles come from a free public collection that may be reused, with a difficulty value on each puzzle so the next puzzle can be easier or harder. The proposed collection is the Lichess puzzle database, which is published for reuse and includes puzzle ratings and themes. This source is one of the approval points in section 12. The puzzles are stored by Lucid so practice does not depend on Lichess being online during a session. Attribution required by the collection’s licence is shown in the product.

### Logic

Logic exercises are written for Lucid. The first version needs a starter bank large enough that the next-exercise rule has both easier and harder items to offer in each kind:

- short challenges with a stored right answer
- longer problems with a prompt and notes for the assistant, not a single official answer

A thin bank that repeats the same item after every attempt does not meet this requirement.

---

## 9. Scores

This is the proposed rule that makes “automatic next exercise” and “longer problems with no single answer” work together. It is an approval point in section 12.

**Chess score.** The number shown is the difficulty of the puzzles the student is currently solving successfully, taken from the public collection’s own difficulty rating. A correct answer raises the target. A miss lowers it. The score is that target, not a level name.

**Logic score.** The number shown is recent accuracy on short challenges only, as a percentage. Those results also choose the next short challenge.

**Longer logic problems.** Completing one is recorded and the planner offers them regularly, but they do not change the logic percentage. There is no honest right/wrong mark for them. The assistant’s reply is the feedback.

---

## 10. Technical requirements

These are constraints for the later build. The framework is chosen after this PRD is approved.

- Students authenticate with Google. Practice, scores, and keys belong to that account.
- A database stores the account, age confirmation, attempts, scores, the next-exercise state, and the logic bank.
- Chess puzzles are imported from the approved public collection.
- Clear-answer checking runs in the product. It does not call Gemini.
- Gemini is called only from the server, with that student’s key and selected model ID.
- The Gemini integration is a separate module with no pages and no shared key. The rest of the product passes it the key, the model ID, the conversation, and any exercise context.
- Keys are encrypted at rest. Logs and API responses never include the full key.
- Model IDs are an allow-list. Any other ID is rejected.
- The assistant fails clearly when the key, the quota, the model, the network, or a safety filter stops the request.
- Pages and the practice loop work without pretending a control does something it does not.

---

## 11. Acceptance for a later build

A build matches this PRD when:

1. A student aged 16 or over can confirm their age, sign in with Google, and return later to the same scores.
2. A student cannot practise until their own Gemini key is accepted.
3. No path uses a shared Gemini key.
4. The model picker offers only `gemini-3.8-flash`, `gemini-3.6-flash`, and `gemini-3.5-flash-lite`, and the chosen ID is the one that answers.
5. A chess puzzle has a real position, a checkable solution, a right/wrong result, and a next puzzle that moves in difficulty with that result.
6. A short logic challenge is checked by the site and affects the logic score.
7. A longer logic problem accepts the student’s own reasoning and returns an assistant reply for that attempt.
8. The dashboard shows the two scores and the next exercise.
9. The student can ask a question that is not about the current exercise and receive a generated reply that can use earlier turns.
10. Asking from an exercise produces an explanation that fits that exercise.
11. An invalid key, a quota error, and a lost connection are understandable and do not wipe the draft.
12. The full API key is absent from the browser source, stored files that are not encrypted, and logs.
13. The interface is dark, consistent, and usable on a phone and on a desktop.
14. Features listed in section 5 are not presented as if they work.

---

## 12. Approve or change these three points

Everything else in this document is a decision you already made. These three are proposals that follow from those decisions. Say yes, or replace them.

1. **Chess source.** Use the Lichess open puzzle database as the free public collection, stored in Lucid, with the required credit.
2. **Scores.** Chess score is the current puzzle difficulty. Logic score is recent accuracy on short challenges. Longer logic problems are tracked and practised, and they do not change that percentage.
3. **Saved keys.** After Google sign-in, the student’s Gemini key is encrypted and kept for that account until they remove it, so they do not paste it on every visit.

---

## 13. Sources for the model list

Checked 6 November 2026:

- https://ai.google.dev/gemini-api/docs/models
- https://ai.google.dev/gemini-api/docs/deprecations
- https://ai.google.dev/gemini-api/docs/pricing
- https://aistudio.google.com/app/apikey
