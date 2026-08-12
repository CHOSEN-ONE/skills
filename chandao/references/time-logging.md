# Chandao Time Logging Rules

## Date Baseline

1. Never create a log for a date later than the system local date. The current date is permitted.
2. Confirm the statutory holiday schedule before deciding whether a date is a workday. Do not infer solely from weekday or weekend.
3. For a month-level review, first report statutory workdays, including make-up workdays, then report statutory holidays and normal rest days.
4. A normal working day targets `8` total hours. A full-day leave is `0`; a half-day leave caps the date at `4`.
5. A non-working day receives no effort by default. User-provided leave or overtime changes the official baseline only when explicit.

## Entry Selection

- One record may not exceed `4` hours. Split a normal day into one or more entries as needed.
- Before writing, query the target year's effort calendar, then re-read any same-date and same-hours candidates to check for identical work content. The calendar's `consumed` field may be numeric while effort detail displays values such as `4 小时`.
- Bind work to a task only when the task title has a strong semantic match. If multiple tasks are plausible, ask. If a narrow customer task is uncertain, use the documented general daily-work task only when that fallback is appropriate.
- For task effort, send a confirmed remaining-hours value. The established default is `999` when the user has not supplied one.

## Verification And Repair

1. Read the create or edit form before POSTing; its fields are the live contract.
2. After a write, re-read the effort record and relevant task or Bug history. Verify date, consumed hours, remaining hours, work content, and object binding.
3. If a record is bound to the wrong task/object or contains corrupted text, identify the bad effort ID, delete it with explicit authorization, create the correct record, then rescan the related histories. Do not leave the bad record or add a compensating duplicate.
4. A response that merely closes a modal, returns HTML, or looks successful is not sufficient verification.
