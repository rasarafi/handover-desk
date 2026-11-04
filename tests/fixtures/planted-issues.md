# Planted issues in handover-desk-demo (answer key)

The auditor must find all of these from the live URL alone. Clean pages must produce no findings.

| # | Issue | Where | Check |
|---|---|---|---|
| 1 | Placeholder copy (lorem ipsum) | `index.html` → "Our story" | text scan |
| 2 | Test account visible to the public | `index.html` team card "Test User / test@test.com"; `dashboard.html` "Signed in as test@test.com" | text scan |
| 3 | Empty dashboard with no empty state | `dashboard.html` bookings table has headers and zero rows | DOM / browser walk |
| 4 | Dead link | `pricing.html` (nav + footer, both pages) returns 404 | link check |
| 5 | Dev URL in shipped JS | `assets/app.js` → `http://localhost:3000/api` | bundle scan |
| 6 | Console error on every page | `assets/app.js` → `window.analytics.track` is undefined (TypeError) | browser console |
| 7 | Missing metadata | `dashboard.html` title is "Untitled"; no favicon or Open Graph tags on any page | head check |

Note: #5 also causes a failed fetch on `dashboard.html`. That is a consequence of #5, not a separate finding.
