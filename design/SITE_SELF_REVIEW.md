# PlanBound Part 2 — self-review

The completed file is **planbound-site.html**, **163,651 bytes** uncompressed (163.651 KB / 159.815 KiB), below the 400 KB limit. It embeds all custom modules, styles, shaders and procedural assets. The permitted Three.js r128 CDN scripts and two Google Fonts remain external dependencies.

Final SHA-256: `af58e20e2482cef6bb832672d33bdc61e5cffec299af266fcc80b1c08357c352`.

The existing Part 1 artifact and its source modules were not edited. `build_site.py` wraps their output with scoped lifecycle hooks, singleton-canvas sizing, live tree/robot state, routing and the new views. No application backend, Cedar policy, canonicalizer, apply-gate implementation or existing test was changed.

## Section 10 acceptance checklist

| # | Result | Actual evidence |
|---|---|---|
| 1 | PASS | All seven named routes and the unknown-route 404 rendered at 1440×900 and 390×844. Browser back/forward returned to the expected views. All 16 screenshots are saved. |
| 2 | PASS | After a 20-navigation loop, callback/subscription counts and GPU resource counts were unchanged. In the instrumented test: 8 frame callbacks, 7 bus subscriptions, 1 store subscriber; hero 25 geometries/13 textures; robot 33/4. Two frame callbacks belong to the test probes. A real 61-second wait verified disposal after 60 seconds away, followed by successful recreation. |
| 3 | PASS | Renderer instrumentation observed at most **one distinct renderer per frame**, including bloom passes. The same robot object, canvas and cable-node array survived Home → Plan Review and hero disposal/recreation. |
| 4 | PASS | Empty resource scope was rejected. Submit stayed disabled without consent. The stored SHA-256 matched recomputation; FNV-1a passed the known `hello` vector `a430d84680aabd0b`. Confirmation also worked with storage blocked and Web Crypto unavailable. |
| 5 | PASS | With a confirmed dev boundary, Sample A produced DENY `s3.public_acl`, REVIEW `sg.open_ingress.dev`, ALLOW `within.boundary`. DENY has no approval action, and a direct sample-engine approval attempt returned false. Approving REVIEW left `1 of 3 changes need attention`. Sample B enabled apply and created four simulated apply records. Sample C, with a confirmed prod boundary including DB instances, produced REVIEW `stateful.destructive` and DENY `sg.open_ingress.prod`. |
| 6 | PASS | Invalid JSON produced an inline error without replacing the active plan. A pasted resource name containing an `img`/`onerror` payload remained text; no image or script execution occurred. Adversarial note text did not expand the selected resource classes. |
| 7 | PASS | APPLIED filtering returned four records. The actual downloaded file parsed as JSON and contained the four filtered apply events. Clipboard JSON was read back successfully in the test browser. Detail, Return to records, search and empty-state clearing worked. |
| 8 | PASS | Returning Home after selecting the clean plan produced an open green gate and three `72e6a1` leaf colors from the store. Seed records now carry computed contract hashes and explicit Sample A plan fingerprints; these were recomputed successfully. |
| 9 | PASS | The shared status chip displayed the active confirmed boundary and gate color across the route screenshots. It is subscribed once to the same store as the views. |
| 10 | PASS | A separate keyboard-only test at 390×844 completed confirmation, approved REVIEW, selected the clean plan, applied it, opened evidence detail, operated an FAQ, dismissed the legal notice, changed story steps and returned Home. Route focus landed on `main`; route announcements were recorded for all 16 captures. This is browser keyboard testing, not an assistive-technology certification. |
| 11 | PASS | Reduced-motion mode completed the wizard without overflow or errors. Transitions and shake are disabled, the story is manually stepped, the original reduced-motion renderer behavior remains, and its controls work. |
| 12 | RISK | Final workflow, recreation and keyboard tests recorded **zero console errors/warnings and zero uncaught page errors**. A 180-frame Home globe sample averaged **8.001 ms**, maximum **14.1 ms**. How it works under real 4× CPU throttling averaged **6.876 ms**, maximum **7.9 ms** over 120 frames. These samples do not prove steady 60 fps through every Home tree/robot pose or on every device; Part 1's broader performance limitation remains. |
| 13 | PASS | All eight routes had no horizontal overflow at 390×844. The keyboard-only test also completed the mobile wizard and Plan Review apply workflow. The robot companion is hidden at this width; the contract, changes and gate remain accessible. |
| 14 | PASS | All browser tests loaded the final site through `file://`. Storage-denied and crypto-fallback execution also passed. External CDN access is needed unless those assets are cached. |
| 15 | RISK | The original globe source and descent equations are reused. Exact camera handoff errors remain **1.1102230246251565e-15** for position and **2.220446049250313e-16** for the look target. Part 1's requested idle motion/parallax remains, so pixel identity with the original static reference is not claimed. |

## Findings fixed during this pass

1. **Native view-transition timeout around WebGL recreation.** Reproduced as a real uncaught Chrome transition timeout. WebGL routes now use the requested CSS wipe; renderer initialization occurs outside the transition update. Other routes use native transitions with explicit recovery. The failing disposal/adaptive-quality/recreation case was rerun with no error.
2. **Empty apply set lacked an event.** If all REVIEW items were rejected, the gate could open with no included resources. Simulated apply now writes an explicit `apply.empty_set` event with `included: []` and the excluded IDs. Ordinary clean-plan apply still generated four records.
3. **Seeded evidence identifiers.** Replaced the illustrative seed hash with the actual computed contract hash and bound those records to the Sample A fingerprint, independent of the currently restored plan.
4. **Disposed renderer during a quality downgrade.** Quality adjustment now skips a disposed hero renderer; a recreated hero inherits the selected DPR tier. This path passed with tier 1 / DPR 0.75 and no errors.

## Deliberate choices and boundaries

- These are the **ordered browser sample rules specified in Part 2**, not a replacement for or integration with the real Cedar/Terraform pipeline. The site makes no infrastructure or AWS API calls. Apply is explicitly simulated.
- The brief gives two conflicting REVIEW-resolution descriptions. This implementation follows the explicit clarification: **Reject is an acknowledged resolution that excludes the change**. Unresolved REVIEW and every DENY close the gate. Resolutions are scoped to both contract hash and plan contents to prevent replay onto a different plan.
- Selecting Sample C never rewrites a confirmed contract. The interface explains that its prod scenario needs a newly confirmed prod boundary with DB instances allowed.
- Only `{contract, planId, resolutions}` is written to sessionStorage. Records, pasted plans, metrics beyond the labeled baseline and notice dismissal remain in memory. The notice stays dismissed across routes in the current page lifetime; a refresh restores it.
- Evidence is capped at 200 records and rendered in chunks of 24. Copy/download failures show a message instead of breaking navigation.
- Legal text is intentionally marked **PLACEHOLDER — replace before launch**, as requested. No production legal completeness is claimed.
- The original Part 1 geometry/styling limitations documented in `SELF_REVIEW.md` remain. They were not redesigned in this extension.
- Testing used installed Windows Chrome. Safari, Firefox, physical mobile devices and audio audition are **UNVERIFIED**.

## Evidence files

- `site-evidence/verification.json`: **30 passing checks**, no failed checks; full lifecycle snapshots, route results, keyboard navigation, hashes, sample outcomes, exported data and CPU profile.
- `site-evidence/final-regression.json`: final artifact hash/size, 16 captures, empty-apply regression, seed hashes, green leaf colors, Home timing, quality/recreation and storage/crypto fallback.
- `site-evidence/keyboard.json`: **8 passing keyboard-only checks**, no page errors.
- `site-evidence/download.json`: the actual downloaded, filtered evidence JSON.
- `site-evidence/index.html`: desktop/mobile screenshot gallery for every route.

Reproduce with `site_verify.py`, `site_regression.py` and `site_keyboard.py` in `design/planbound/`. The full verification waits 61 real seconds to test disposal; it does not fake that timer. The final regression separately invokes disposal directly to exercise the quality-tier edge case.
