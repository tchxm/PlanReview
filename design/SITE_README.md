# PlanBound Part 2 — complete sample website

Open **planbound-site.html** in Chrome. Click **CLICK TO START**. No build, backend, AWS account or credentials are required. An internet connection is needed to load the permitted Three.js scripts and Google Fonts.

This file contains the complete website. `planbound.html` remains the earlier Part 1 deliverable. `SITE_DELIVERABLE.md` contains the complete Part 2 source in one HTML code block.

## Try the complete workflow

1. Open **Menu → Contract**. Keep **dev**, the three selected resource classes, and blast radius **5**.
2. Click **Confirm boundary**, check the consent checkbox, then click **Submit confirmed boundary**. You should see a confirmation stamp and a 12-character contract hash.
3. Open **Plan Review**. **Sample A** shows S3 **DENY**, security group **REVIEW**, and IAM **ALLOW**, each with its matched rule.
4. Approve the REVIEW. The gate still stays closed because the S3 DENY remains. A DENY has no approval button.
5. Choose **Sample B · clean plan**. All four changes are ALLOW, the gate turns green, and **Apply Changes** becomes enabled.
6. Click **Apply Changes**. Expect **Applied (simulated)**. Nothing is deployed.
7. Open **Evidence**, choose **APPLIED**, inspect a record, and try **Copy JSON** or **Download JSON**.
8. Return Home and scroll into the tree. Its gate is open and the three verdict leaves are green because they read the same store.

For **Sample C**, define another boundary first: select **prod**, include **db_instance**, confirm it, then load Sample C. The database replacement is REVIEW and unrestricted ingress is DENY. Selecting a plan never silently changes a confirmed boundary.

Rejecting a REVIEW explicitly excludes it from the apply set. A rejected REVIEW counts as resolved; unresolved REVIEW and every DENY keep the gate closed. An all-rejected set produces an explicit empty simulated-apply record.

## Routes and controls

- `#/` — globe, tree, reviewer and live session summary.
- `#/how-it-works` — Define → Inspect → Apply story.
- `#/contract` — boundary wizard.
- `#/plan-review` — sample plans, pasted normalized changes, resolutions and simulated apply.
- `#/evidence` — filters, search, record details and export.
- `#/about` — original editorial copy, principles and FAQ.
- `#/legal` — clearly marked pre-launch legal placeholders and sample-data notice.
- Any unknown route — 404.

Press **g**, then **h/c/p/e/a** to navigate. **?** opens keyboard help. **M** toggles sound. In Plan Review, **j/k** select a row; **a/r/e** approve, reject or explain it. Typing in form controls does not trigger these shortcuts.

## Optional HTTP preview

From the project root:

```powershell
python -m http.server 8011 --bind 127.0.0.1 --directory design
```

Open http://127.0.0.1:8011/planbound-site.html.

## Scope and persistence

The rules are the deterministic **browser sample rules requested in Part 2**. This site does not call the existing Cedar/Terraform/Ollama backend. Every sample plan, evidence tile, counter baseline and simulated apply is labeled SAMPLE DATA.

Only the contract, selected sample-plan identifier and scoped resolutions are persisted in sessionStorage. Pasted plan contents, accumulated evidence and the sample-notice dismissal remain in memory. Refreshing rebuilds the seed evidence and evaluates the selected sample again. If storage is blocked, the site still works.

The original Part 1 sources and output are unchanged. `planbound/build_site.py` wraps that output with the `site-*.js` modules and `site.css`; it emits one self-contained custom-code HTML file. The browser tests are `site_verify.py` and `site_regression.py`, using Python Playwright and installed Chrome.
