# Verification

The story tested is: website URL → saved company analysis → editable brief → community discovery and ranked results → platform-specific searches.

## Live provider and browser checks

Claude Sonnet 5.5 and its native search/fetch tools were exercised using the existing local configuration. Credentials were kept outside this repository.

- **Cnvrted company brief:** read five first-party pages and identified founders, B2B sales teams and service-business owners. The first deeper prompt over-interpreted customer examples; the final implementation requires facet-specific targeting evidence for industry, size and markets. The corrected brief leaves those fields unknown.
- **Buffer company brief:** read four first-party pages and produced different roles: creators, small business owners, agency/social media managers, nonprofit communications, education social teams and API developers. It did not manufacture a geography or ideal-customer industry from customer examples.
- **All-platform Cnvrted results:** 10 ranked suggestions from 144 matching catalog candidates, with The GTM Club first at 90/100. The model was allowed to return fewer than 18 useful suggestions.
- **Slack view:** 10 ranked suggestions from 40 matching candidates. Every returned row was classified Slack. The GTM Club, RevGenius and Instantly were the leading suggestions.
- **Discord view:** nine ranked suggestions from 29 matching candidates. Every returned row was classified Discord. Class of One led at 78/100; broader founder groups were labeled conditional and scored lower.
- Scores were numeric, bounded to 0–100 and displayed in descending order with rank numbers. They are relevance estimates, not conversion probabilities.
- Reloading the browser and restarting the server restored the saved company brief, selected platform and existing result without another company scrape.
- Slack and Discord SVG logos loaded from local asset routes.
- At 1280×900 and 390×844, document width matched viewport width. The temporary viewport override was reset after testing.
- The settings dialog showed the selected Sonnet model while its saved-key field remained empty.
- Export downloaded valid JSON with ten Slack recommendations. No credentials were included in the result object.

## Automated checks

`python3 -m unittest discover -s app -v`: **32 passing tests**.

`node --check app/static/app.js`: passed.

Coverage includes the two-stage flow, authoritative user corrections, platform scoping without re-fetching the company, fit-score bounds/order, empty/weak matches, exact ICP/access evidence, customer-example rejection, source retrieval and native tool errors, duplicate handling, restrictions, feedback isolation, private-address rejection and local persistence.

## Screenshots

- [Entry page](website.png)
- [Company brief](company.png)
- [Desktop recommendations](communities-desktop.png)
- [Mobile recommendations](communities-mobile.png)
- [Discord recommendations](discord.png)

Detailed non-secret check results are in [verification.json](verification.json).

## Limits

The catalog contains research candidates, many based on directory descriptions. Joining, private member activity, current eligibility and permission to promote were not tested. A 90/100 fit score is not a promise of access or customers. The app inspects a bounded number of pages per discovery pass; it does not claim exhaustive internet coverage. Pending same-name identity conflicts require editorial review, and the local server must remain running for optional daily refresh.

The GitHub connection used for the initial push could not create workflow files because it lacks the `workflow` permission. The optional CI configuration is supplied as `checks.example.yml`; local checks above were executed successfully.
