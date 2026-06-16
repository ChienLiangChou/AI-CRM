# SKC CRM Watchlist Data Source Plan

This CRM can already store client watchlists, run scheduled checks, create Codex-app notification records, generate CRM/Gmail drafts, and keep Gmail sending behind review gates. The remaining production dependency is a reliable listing and sold/leased-comps source.

## Recommended Path

1. Use REALM/TRREB saved searches or exported CSV as the near-term source.
   - This is the best short-term method because it uses Kevin's authorized brokerage tools instead of scraping public sites.
   - The Watchlists page supports CSV import, pasted listing-feed text, authorized RESO/OData MLS JSON preview/import, Gmail saved-search preview/import, and per-watchlist Gmail source queries.
   - Use the Watchlists page Source Kit download to get all active client templates plus the drop-folder instructions in one zip.
   - The scheduled Codex automation also supports an authorized CSV/JSON drop folder: `/Users/kevinchou/SKC Agent OS/backend/watchlist-imports`.
   - Put REALM/TRREB CSV exports or authorized RESO/OData JSON exports in that folder, or save completed per-client source files as `.csv` / `.json` beside the disabled template in `watchlist-imports/source-templates/`; the 9/3/6 automation will import new file hashes before running watchlist matching.
   - Keep Gmail saved-search import off until Kevin explicitly enables it from the Watchlists page.

2. Use a formal MLS/RESO/TRREB data connector as the long-term source.
   - This should be implemented only after confirming the allowed data access path and terms.
   - The backend already has a connector-ready adapter at `/api/properties/import-reso-json` for authorized RESO/OData JSON payloads such as `{ "value": [...] }`.
   - The scheduled Codex automation has a disabled-by-default RESO/OData HTTP connector that can call an authorized JSON endpoint and route it through the same adapter.
   - Use the adapter in dry-run mode first so Kevin can review mapped rows, warnings, and watchlist match previews before anything is stored.
   - Public website scraping is not the preferred production method for sold prices or client-facing comp alerts.

## Optional RESO/OData Connector

The formal connector is intentionally off unless Kevin explicitly configures an authorized data feed. Do not enable it with public website URLs or scraped MLS pages.

Set these only after the provider/brokerage confirms the endpoint is allowed for this use:

```bash
WATCHLIST_RESO_CONNECTOR_ENABLED=true
WATCHLIST_RESO_CONNECTOR_URL="https://authorized-provider.example/odata/Property?...approved filters..."
WATCHLIST_RESO_CONNECTOR_BEARER_TOKEN="provider-issued-token"
```

Optional overrides:

```bash
WATCHLIST_RESO_CONNECTOR_AUTH_HEADER="Authorization"
WATCHLIST_RESO_CONNECTOR_AUTH_PREFIX="Bearer"
RESO_ACCESS_TOKEN="provider-issued-token"
```

When enabled, the scheduled automation fetches JSON from `WATCHLIST_RESO_CONNECTOR_URL`, sends it to `/api/properties/import-reso-json`, and then immediately checks all active watchlists if any rows were created or updated. The automation redacts query strings in logs and still does not send Gmail or approve drafts.

3. Keep client delivery draft-gated by default.
   - New watchlists default to Auto Gmail Draft Only: matches can create Gmail drafts for review, but do not send.
   - Manual review remains available when Kevin wants no draft until after reviewing the alert.
   - Auto Send Armed still requires `WATCHLIST_AUTO_SEND_ENABLED=true` on the backend before any Gmail send can happen.

## Current Operating Loop

1. A client watchlist stores criteria such as area, property type, price, bedrooms, parking, subject property, deal breakers, schedule, notification channel, review mode, and source query.
2. A data source import creates or updates rows in `properties`.
3. The scheduled automation runs `check_watchlists.py`.
4. The automation imports new CSV and RESO/OData JSON files from `/Users/kevinchou/SKC Agent OS/backend/watchlist-imports` and its source subfolders, using SHA-256 state to avoid reprocessing the same export.
5. If `WATCHLIST_RESO_CONNECTOR_ENABLED=true`, the automation also fetches the authorized RESO/OData connector and imports it through the same backend mapping adapter.
6. The backend checks due watchlists, or all active watchlists when a source import created/updated rows, scores matching properties, deduplicates previous alerts, and creates `watchlist_alerts`.
7. Codex-app notifications are written as `queued_for_codex_report`; the automation reports them in Codex and marks them `reported_in_codex`.
8. In Auto Gmail Draft Only mode, the backend creates a reviewable Gmail draft when a match is found; Kevin can still dismiss or edit before sending.
9. Sending requires an existing Gmail draft id unless the watchlist is explicitly in auto-send mode and the server auto-send env flag is enabled.
10. From a Codex app notification, Kevin can approve an already-reviewed Gmail draft by asking Codex to run:
   `python3 /Users/kevinchou/.codex/automations/skc-crm-watchlist-check/review_watchlist_alert.py send --alert-id ALERT_ID --confirm '沒有問題'`.
   If the contact has exactly one ready Gmail draft, Kevin can also use:
   `python3 /Users/kevinchou/.codex/automations/skc-crm-watchlist-check/review_watchlist_alert.py send --contact 'Tom Lin' --confirm '沒有問題'`.
   Both commands still call the review-gated backend send endpoint and refuse to send without a valid confirmation phrase or an existing Gmail draft. If a contact has multiple distinct ready drafts, the shortcut blocks and asks for the exact alert id.
11. Kevin can also ask Codex to run a safe manual check for a specific client:
   `python3 /Users/kevinchou/.codex/automations/skc-crm-watchlist-check/check_watchlists.py check --contact 'Tom Lin'`.
   This imports enabled source feeds, checks only the selected contact's watchlists, reports any new alerts, and prints the next review command. It does not send Gmail, approve drafts, or mark alerts as sent.
   To check the existing source rows without importing the drop folder or Gmail feed first, use:
   `python3 /Users/kevinchou/.codex/automations/skc-crm-watchlist-check/check_watchlists.py check --contact 'Tom Lin' --skip-source-import`.

## Data Source Readiness Rules

Buyer watchlists need active for-sale rows with address, city, property type, list price, beds, baths, and parking.

Seller watchlists need active competing listing rows and sold comparable rows with list/sold prices near the subject property.

Tenant watchlists need active rental listing rows with address, city, property type, monthly rent, beds, baths, and parking.

Landlord watchlists need active rental rows and leased comparable rows with monthly rent and core property details.

## Safer Alternative To Scraping

The better production approach is:

1. Create REALM/TRREB saved searches for each client or watchlist class.
2. Download the Watchlists page Source Kit and use the included per-client templates as field guides.
3. Export the REALM/TRREB results to CSV or authorized RESO/OData JSON and drop them into `/Users/kevinchou/SKC Agent OS/backend/watchlist-imports`, save completed per-client `.csv` / `.json` files beside their disabled templates in `source-templates/`, paste an authorized RESO/OData JSON result into the Watchlists page, or send saved-search emails to the connected Gmail account.
4. Prefer the local drop folder when Kevin wants the lowest-risk path without enabling Gmail feed reading.
5. Preview the per-watchlist Gmail query in the Watchlists page if using saved-search email import.
6. Import the feed only after preview confirms the parsed rows are correct.
7. Let scheduled Codex automation report matches and draft recommendations.
8. Move to a formal MLS connector when Kevin has the right authorized data path.

This keeps client-facing recommendations grounded in authorized listing data, avoids brittle public scraping, and preserves Kevin's review boundary before client communication.
