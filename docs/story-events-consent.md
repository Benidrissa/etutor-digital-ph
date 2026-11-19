# Story events: what is stored, for how long, and what is left to decide (#2711)

Story mode asks a learner to bet on what will happen before it is explained.
To know whether that helps, the app reports three kinds of events about a story.
This note says exactly what they hold. It is a description of the code, not
legal advice: the consent wording for learners under 14 and the retention
period are decisions for the owner and the data-protection lead (GDPR, Senegal
Loi 2008-12, Ghana Data Protection Act 2012, Nigeria NDPR 2019, Côte d'Ivoire
Loi n°2013-450 are the frameworks the project already targets).

## What is stored

One row in `usage_events` (the existing analytics table) per event:

| Event | Fields |
|---|---|
| `story_prediction` | story id, chapter id, question id, language, `matched` (the bet matched what the demo showed: true/false) |
| `story_first_try` | story id, chapter id, question id, language, `correct` (first answer right: true/false), `attempts` (1) |
| `story_chapter_complete` | story id, chapter id, language, `stars` (0 to 3) |

Every row also has `anonymised: true`, a timestamp and an id of its own.

- **No user and no session.** `user_id` and `session_id` are NULL. The request is
  signed in (so the server can read the learner's opt-out and refuse strangers),
  then the identity is dropped before the row is written. Nothing links two
  events of the same learner, so only rates can be measured (how often a bet
  matches, how often a first answer is right), not one child's path.
- **No free text.** The route accepts a closed list of fields (anything else is
  refused with 422). Ids must look like identifiers (letters, digits, `.`, `_`,
  `:`, `-`). The learner's name, their friend's name and what they typed are
  never sent.
- **Nothing about the device**, the IP address is not stored by this route.

The story id, chapter id and question id are identifiers of the course content.

## Opt-out

The learner's existing analytics opt-out (`users.analytics_opt_out`, set in the
profile, mirrored in the browser as `analytics_opt_out`) is honoured twice: the
browser neither sends nor queues story events, and the server stores nothing
for a user who opted out.

## Offline

An event that cannot be sent (no connection, a network error) is queued in the
browser (IndexedDB, `offline_actions`, type `story_events`) and sent when the
connection returns. It holds the same fields as above. A queued event is
deleted once sent.

## How long

There is **no automatic expiry** on `usage_events` today. The function
`story_events.purge_story_events(db, older_than_days=N)` deletes story events
older than N days; it is not scheduled. A retention period has to be chosen and
a schedule added before the events are collected from children at scale.
Because the rows hold no identity, a learner's request to delete "their" events
cannot be answered row by row: say so in the consent text.

## What is left to the owner before the pilot with children

- The consent wording for learners under 14, and who gives it (parent, teacher or
  school), per country.
- The retention period, and the schedule that applies it.
- Whether the pilot with 5 to 8 children (with consent) runs with these events
  on, or with a paper observation sheet only. That test is not part of the code
  change and has not been done.
