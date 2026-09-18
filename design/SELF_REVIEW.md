# PlanBound acceptance self-review

Tested the actual standalone HTML from `file://` in installed Chrome, headless, at 1440 × 900 and an emulated 390 × 844 touch viewport. WebGL reported **Intel UHD Graphics / ANGLE / Direct3D11**. This report covers the design prototype, not the separate application backend.

The final artifact is `planbound.html`. `DELIVERABLE.md` contains its complete source in one fenced HTML block. All custom CSS, JavaScript, shaders and procedural assets are embedded; the permitted Three.js r128 scripts and Google Fonts require network access.

## Acceptance checklist

| # | Result | Evidence and limits |
|---|---|---|
| 1 | PASS | Boot logs real context, lattice, link, tree, robot and compile calls. Ready was reached at 1.61 s in the final acceptance run. Click starts; Escape independently tested. Compile completion means the API call returned, not a separate GPU completion fence. |
| 2 | RISK | Original globe geometry, shells, links, orbits and palette are retained. `p-0.00.png` was inspected. Requested idle yaw, breathing and pointer parallax change framing over time, so this is not a claim of pixel identity to the base. |
| 3 | PASS | Exact rail-start position error **1.1102230246251565e-15**; look-target error **2.220446049250313e-16**. The captured damped progress near 0.30 also reaches the endpoint within 1e-4. This checks position continuity, not derivative continuity. |
| 4 | RISK | Six primary paths, timed cards, projected leaders and station travel work. Growth uses a six-spoke seed scaffold rather than a single unbranched initial trunk. Cards are clamped into the viewport instead of using a full collision/occlusion solver. |
| 5 | RISK | Screenshot `verdict-fork.png` shows green/amber/red branches and the DENY ring. The three semantic tips use explicit offsets from the feature terminal, not the requested angularly sampled sibling terminals of the colonization tree. |
| 6 | PASS | `canopy-closed.png` at p≈0.95 shows the converging paths, closed ring and lock. The illustrative apply button remains disabled with DENY present. |
| 7 | PASS | Two independent reloads produced the same **2,897 segments** and identical node-coordinate SHA-256: `387fe109731f2625b73aecd85ce7fca5282aa6c499a4702e0711c453edd65af0`. |
| 8 | PASS | Clicking station 03 reached p≈0.60507935, showed `03 / 06` and activated `Boundary engine`. Its evidence button opened the dialog. |
| 9 | PASS | Surface spring displacement and nearest-hub highlights were inspected in the globe capture. The interaction weight reaches zero at p=0.30. The update uses typed position buffers. |
| 10 | PASS | Browser observed TRACK with nonzero head rotation and IDLE after inactivity; seven cable meshes follow the procedural head. The robot has **27,932 rendered triangles**. It is a stylized procedural interpretation, not a photorealistic reproduction. |
| 11 | RISK | Fast movement produced CURIOUS; clicking produced ACK and cable motion. Web Audio synthesis is implemented, but audible output was not auditioned through speakers in this headless test. |
| 12 | PASS | Actual chip hover followed by visiting the robot produced green ALLOW, amber REVIEW and red DENY. See `unit-allow.png`, `unit-review.png`, `unit-deny.png`. |
| 13 | PASS | Robot context reports LOOK; evidence-card context shows OPEN in the screenshots. Dot/ring and magnetic controls use the shared animation loop. |
| 14 | PASS | Reduced-motion mode exposes six readable feature entries, disables moving effects, and keeps the camera unchanged when the pointer moves. Mobile and reduced layouts have no horizontal overflow. Forced WebGL failure opens the readable fallback without an uncaught exception. |
| 15 | RISK | Intel UHD rolling frame samples were **8.9–21.4 ms**; a steady 60 fps across scenes is not achieved/proven. Real 4× CPU tests did not remain over the 22 ms threshold, so no natural tier switch occurred. A separately labeled controlled 40 ms sample test activated tiers 1→5 without errors. Final canopy cost is **24 draw calls including bloom**, but this is not an all-progress worst-case guarantee. |
| 16 | PASS | Normal browser console and page-error lists are empty. After warming every scene and scrolling for **60.42 seconds**, hero memory stayed at **26 geometries / 13 textures**, robot at **33 / 4**. This is renderer resource stability, not a claim about all JavaScript heap allocations. |
| 17 | PASS | All browser verification loaded the final HTML directly through `file://`. No application server or credentials were needed. CDN access is still necessary for WebGL libraries and the two fonts. |

## Other implementation limits

- Position continuity is verified; camera velocity/tangent continuity is not. The ignition move is a short lateral arc rather than a fitted camera roll.
- The colonization algorithm uses a spatial hash and duplicate-node suppression, with growth scheduled in chunks. A single iteration and final geometry/shader construction are not guaranteed to stay below 6 ms.
- Pipe-model radii are sampled along the primary tubes. Main paths and capillaries are merged, but the selected paths can share geometry near their origin.
- The original 1,800 lattice/hub points remain; the separate requested packet layer adds 150 points and the hover highlight adds three. A literal global 1,800-point cap would require reallocating that budget.
- The robot uses approximate fixed collision volumes for its cables. Offscreen rendering pauses; optional distant-scene disposal is not implemented. Library raycasts/normal updates can allocate internally, so strict zero-allocation rendering is not claimed.
- Base review resources and tree evidence now agree: IAM permission restriction → ALLOW, security-group restriction outside scope → REVIEW, S3 private-to-public ACL → DENY. These are labeled illustrative data, not fresh Cedar evaluations.
- This delivery extends the supplied base document in isolation. Existing canonicalizer, policies, apply gate, API, tests and React frontend were not modified.

## Reproducible evidence

- `evidence/verification.json`: boot timings, deterministic tree, station action, interactions, 60-second resources, real CPU-throttle run, mobile/reduced/fallback results.
- `evidence/screenshots.json`: captured scroll positions and camera coordinates, exact continuity calculation.
- `evidence/supplemental.json`: Escape, bloom-inclusive draw calls, TRACK, robot CPU throttle, explicitly controlled tier test and reduced camera test.
- `evidence/console.json`: final screenshot-run console messages.
- Required captures: `boot.png`, `p-0.00.png`, `p-0.30.png`, `p-0.50.png`, `p-0.90.png`, `unit.png`.
- Additional captures: `verdict-fork.png`, `canopy-closed.png`, `unit-allow.png`, `unit-review.png`, `unit-deny.png`, `mobile.png`, `reduced.png`, `fallback.png`.

Run `design/planbound/acceptance.py`, `verify.py` and `supplemental.py` with the project Python environment to repeat these checks. They require the Python Playwright package and installed Chrome. The controlled tier test changes only its own temporary browser session.
