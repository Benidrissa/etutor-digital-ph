# Story director script, grammar v0

Status: draft for the paper test of #2737 (epic #2734). Linear mode only. This
document is the contract the throwaway parser of the spike
(`backend/scripts/story_script_grammar.py`) implements; the production parser
(#2746) starts from it. If the paper test fails, nothing here ships and story
mode stays on the slots builder (#2713).

## What a script is

For each chapter the model writes a short list of lines, about 70, about 40 of
them lines said by characters. Code writes everything else: the header below,
the marks, entrances, framing and reactions, and the checks. A line holds one
statement. A wrong line is repaired alone.

```
macro  positional...  key=value...  "text"
macro  positional...  key=value...  "texte" | "text"      (pair form)
```

- Blank lines and lines starting with `#` are ignored.
- A text is in double quotes; a quote inside a text is written `\"`.
- Positional arguments, `key=value` arguments and texts may come in any order
  after the macro name; by convention positional first, then text, then keys.
- A value has no space. A list is written with commas (`cast=hero,friend`) or,
  for numbers, semicolons (`mark=3;7;12`).

## Roles and moods

Scripts name roles only: `hero`, `friend`, `family`, `mentor`, `tutor`. First
names are put in at display time. The hero stays the learner. A role must be in
the chapter's cast (the header) and on stage in the current scene to speak or
point.

`mood` is one of `talk` (default), `happy`, `think`, `surprised`, `sad`.

## The two-language form

A text is either one string, or, in the pair form, two strings separated by
`|`: `"Un nombre trop long !" | "A number too long!"`. The header says which
form a chapter uses and in which order (first the language of instruction).
The character limit applies to each language of a pair. A script in the pair
form costs about twice the output of a one-language script; the paper test
measures it.

## Macros

| Macro | Arguments | Text | Limit | Meaning |
|---|---|---|---|---|
| `scene` | `<place>` `cast=<roles>` | none | | Change of place; 2 or 3 different roles on stage. The first statement of a script. |
| `say` | `<role>` `[mood=]` | one | 60 | A line said by a character on stage. |
| `narrate` | | one | 90 | Stage direction, present tense. |
| `mistake` | `<role>` `[mood=]` | one | 60 | A character says the wrong idea. Never the hero: the learner bets freely, the machine settles it. |
| `show` | `<object>` `[at=<mark>]` | none | | An object of the menu comes on stage. |
| `machine` | `<machine>` data `[reveal=]` | none | | An idea machine starts. Data: at least one of `n`, `a`, `b`, `from`, `to`, `mark`. |
| `point` | `<role>` `target=<target>` | none | | A character points at `machine.<part>` or at an object. |
| `card` | `<card>` | none | | The card of a beat is written (its title and rows come from the plan). |
| `bet` | `<Lk>` | none | | The learner bets on the open question before the answer shows. |
| `ask` | `<Qi> [<Qj> ...]` | none | | Place quiz questions (each is a full question: check, cheer, second try, reward). |
| `game` | | none | | The chapter's game. Not offered by the spike's header. |
| `reward` | | none | | A reward moment. |
| `open` | `<Lk>` | one | 90 | Raise a story question, in the model's words. |
| `close` | `<Lk>` | none | | The question is answered here. |
| `teaser` | | one | 90 | One sentence that states the next topic. It does not end with a question mark. Last statement of the chapter. |
| `recap`, `cliff` | `<Lk>` | none | | Open-loop macros (#2751). Parsed, refused in linear mode (`mode_refused`). |

Marks: `left`, `centre`, `right`, `off`. Reveals: `groups`, `columns`, `steps`, `all`.
Question ids: `L1`... are story questions the header opens and closes; `Q1`...
are quiz questions the header places. Ids are from the header or the menu,
never invented.

### Limits

About 70 statements, never more than 80 (`too_many_lines`; warning above 70).
About 40 said lines (warning outside 25 to 50). A said line (`say`, `mistake`)
has at most 60 characters, in each language.

## The header that code imposes

A chapter's script is checked against a header built by code, never written by
the model. In the spike a person assigns by hand what the code of #2749 and
#2746 will assign later.

| Field | Content |
|---|---|
| `languages` | `["fr"]`, or `["fr","en"]` for the pair form. |
| `stages` | The journey stages the chapter plays (table of #2749; `distribute_stages`). Each stage requires blocks: `bet` + `mistake` at 3 and 8, `machine` at 5, `card` at 9, `ask` at 6 and 11, `teaser` at 12. `ask` is also required whenever quiz questions are listed. |
| `opens` / `closes` | Story questions to raise (`L1`..., with a hint of their content) and to answer. In linear mode each chapter closes what it opens. |
| `quiz` | Quiz questions to place, each exactly once. |
| `cards` | Cards to place, each exactly once (id and title). |
| `cast`, `places`, `objects`, `machines` | The menu. In the spike it is hand-made from what exists today: cast roles of the course, the 7 stock places, the drawn visuals (plus `place_value` and `number_line` for maths), the lesson's figures and the plan's props. The library menu is #2742. |
| `numbers` | Numbers found in the lesson's facts and quiz. A machine's numbers outside this set raise a warning. |
| `bets` | For each opened question, the bet's two choices; see below. |

## The bet

`bet Lk` carries only the id of the open question. Its choices and its verdict
are not written by the model.

- Choices: the right one is the beat's `discovery`; the wrong one is the
  beat's `problem` (or the chapter's `obstacle`); the third is always "I don't
  know" (`Je ne sais pas`). The stored lessons hold no misconception field, so
  where `problem` is missing or poor, a person writes one wrong choice per
  question in `assignments.json` (`wrong`).
- Verdict: the first `machine` after the `bet` settles it, the same way for
  every learner. The `mistake` line that follows the bet is said by a
  character and is the wrong choice in words.
- Order: `open`, `bet`, `mistake`, `machine`, `point`, `card`, `close`.
- Today `story_poe.build_bet` builds a bet only from a demo's data. How the
  production lowering builds this bet is decided in #2746; if it cannot, `bet`
  lowers to a plain open question and the validator says so.

## Errors and repair

Every error carries a line number, a stable code and a message that goes back
to the model as it is. Line 0 means the script as a whole lacks something.

```
line 12 [too_long] error: say: the fr text has 74 characters, the limit is 60
  > say hero "..." mood=happy
script [question_missing] error: quiz question Q2 is never asked (ask Q2)
```

Codes: `bad_syntax`, `duplicate_arg`, `unknown_macro`, `bad_arity`,
`unknown_arg`, `missing_arg`, `bad_value`, `unknown_role`, `role_not_in_cast`,
`cast_size`, `unknown_place`, `unknown_object`, `unknown_machine`,
`unknown_card`, `unknown_question`, `text_count`, `text_empty`,
`text_unexpected`, `too_long`, `too_many_lines`, `scene_first`,
`speaker_off_stage`, `mistake_by_hero`, `open_twice`, `close_before_open`,
`close_twice`, `bet_without_open`, `bet_twice`, `question_twice`,
`card_twice`, `target_unknown`, `teaser_is_question`, `teaser_not_last`,
`mode_refused`, `loop_state`, and for the script as a whole `empty`,
`open_missing`, `close_missing`, `question_missing`, `card_missing`,
`block_missing`.

Warnings never make a script invalid: `lines_over_target`, `dialogue_count`,
`card_before_picture`, `order_bet_machine_card`, `silent_run` (more than 3 lines
without a visible change), `deictic_without_target` (a line says "this" or
"look" with nothing pointed at), `number_not_in_facts`. They are the
approximate form of the epic's picture checks; once calibrated, a chapter
under the threshold is repaired.

Repair: one call per faulty line, which sends that line, its error and the
line before it, and expects the corrected line or `DELETE`. What is missing
(line 0) is one more call that returns the missing lines, inserted before a
final `teaser`. One round only: a script is valid after repair or it is not.

## The 17-line example

The example of the epic, parsed as is by the spike (its test). It runs with
header `opens = L1, L2`, `closes = L1`, quiz `Q1`, `Q2`, card `groups_of_three`,
and in open-loop mode, since it ends on a `cliff`. In linear mode the `cliff`
is refused (`mode_refused`) and `L2` would be left open.

```
scene family_home  cast=hero,friend,family
say family  "Une nouvelle route coûtera 4 305 892 176 FCFA !"  mood=surprised
open L1  "Comment lit-on un nombre aussi long ?"
bet L1
mistake friend  "Quatre mille... trois cents ?"
machine place_value  n=4305892176  reveal=groups
point hero  target=machine.millions
say hero  "Des groupes de trois, en partant de la droite !"  mood=happy
close L1
card groups_of_three
ask Q1 Q2
scene market  cast=hero,friend
show cash_register
say friend  "La caisse affiche 45 millions, l'enseigne 4,5 !"  mood=surprised
open L2  "Qui a raison ?"
bet L2
cliff L2
```

It is 17 lines, `scene` lines included.

## Not in v0

Loops in lowering (#2751), lowering itself and the cue contract (#2746,
#2739), the library menu (#2742), the translation call (#2748: v0 only
measures a script written in two languages at once), a `game` in the header,
and a grammar for non-linear stories.
