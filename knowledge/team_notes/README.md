# Team notes

Short Markdown notes that fill the gaps the Ask Product bot reports.

How the loop works:

1. Someone asks the bot a question it can't answer from the docs, Jira or meeting notes.
2. The bot says so instead of guessing, and logs the question in `state/questions.jsonl`.
3. The weekly report and `python -m autopilot gaps` list the questions that are still unanswered and how often each was asked.
4. The owner writes a note here, one `.md` file per topic. Each `#` heading becomes a searchable section.
5. The next time anyone asks, the bot answers from the note and links it as the source.

Keep each note short and factual, and put the date and owner at the top so stale notes are easy to spot.
This README isn't indexed.
