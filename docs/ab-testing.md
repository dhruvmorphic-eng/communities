# First A/B experiment: community-v1

Implemented 2026-10-20. This is an experiment harness, not a finding that one design is better.

## Treatments and hypotheses

A stable random browser ID is saved in localStorage. The server independently hashes it into two 50/50 assignments, giving four combinations. Assignments persist in SQLite and across reloads. The browser cannot choose its treatment through a request parameter.

| Dimension | Control | Treatment | Hypothesis |
| --- | --- | --- | --- |
| UI | Full company-review form | Offer, buyers and goal visible; extra buyer fields, strategy and evidence expandable | Fewer visible fields improves completion without reducing useful results |
| Recommendations | Existing balanced relevance prompt | Same candidates and eligibility rules, with stricter explicit buyer-evidence instructions | More visitors find at least one useful recommendation |

Both UI variants still let users review and correct the company before discovery. Both ranking variants use the same underlying model, sources, discovery budget and safety exclusions. The ranking treatment is a prompt change; lower/higher AI fit scores are not the success metric. Neither variant promises customers or permission to promote.

## Recorded events

Scan started → analysis ready → brief confirmed → results viewed → community clicked / Useful / Hide. Job failures are recorded as a guardrail. Completed-job events must match the visitor and flow; community interactions must reference an actual recommendation in that job. Repeated events are deduplicated. Reports count unique visitors, not raw clicks.

Use **A/B results** in the app footer. The report shows:

- UI primary: visitors who view results / visitors who start a scan.
- Ranking primary: visitors marking at least one result Useful / visitors viewing AI-ranked results.
- Secondary: community click-through; Hide rate; failures and intermediate funnel counts in raw data.
- Zero denominators display an em dash, not a fabricated 0%.

Basic fallback results still count toward UI completion, but are excluded from the ranking comparison. Historical jobs without experiment attribution do not count. A community link click records interest, not a confirmed join, lead or sale. Useful and Hide are independent events; a visitor can do both on different results.

The report is descriptive. It has no significance calculation or automatic winner. Initial local developer checks are test activity, not customer evidence.

## Run a real test

1. Complete the existing production requirements (authentication, isolation and hosting) before routing public traffic to this localhost prototype. Keep experiment data server-side and distinguish QA/internal accounts from actual participants in that deployment.
2. Run a small pilot to establish completion/usefulness baselines and inspect event loss, device issues and the allocation balance. Fix tracking before measuring lift.
3. Before the decision experiment, define the smallest worthwhile improvement, calculate the required sample size from the baseline, choose a fixed observation window, and freeze this experiment version, model and prompts. Account for two primary hypotheses and inspect the four combinations for interactions.
4. Recruit a mix of industries and company types. Do not compare a handful of repeated scans of your own company as if they were independent customers. Keep free and paid equally eligible.
5. Compare outcomes only after visitors have had the same follow-up window. Check Hide rate, failures, empty results and usefulness before shipping a completion-only winner. Analyze missing feedback as missing; no feedback is not an explicit negative rating.
6. If the catalog, provider or model changes substantially, record the change and start a new experiment version. Shared catalog discoveries and existing company feedback can affect subsequent visitors; use frozen candidate snapshots for a controlled offline ranking evaluation.

For offline recommendation evaluation, use identical confirmed briefs and frozen candidates for both prompts, shuffle/anonymize their outputs, and ask independent reviewers to judge buyer overlap, source support, access eligibility and practical usefulness. Include AI/GTM software, payroll/HR, a creative service business and businesses outside tech. This complements the online behavior test; it does not replace it.

## Data and limits

Events contain an anonymous browser ID, flow/job/community IDs, treatment labels and timestamp. They do not include website URLs, email addresses, company briefs or API keys. Stored locally in the ignored SQLite database; no third-party analytics SDK. Browser IDs are pseudonymous, not a real user identity. Clearing browser storage or switching devices creates a new participant. Both existing company feedback and the catalog remain shared in this single-user prototype.

The API exposes aggregate results via GET /api/experiments and accepts same-origin, CSRF-protected assignments/events. This server intentionally listens on localhost only. No public traffic or customer outcome was generated by implementing this test.
