# PlanBound standalone design

Open `planbound.html` in Chrome. Wait for **CLICK TO START**, click it, then scroll slowly.

The sequence is: original globe → camera descent → six feature stations → closed gate → CRT reviewer → original editorial/review sections. The numbered dots jump between stations. **Open evidence** opens an illustrative record. Move over the reviewer, move quickly, and click to see TRACK, CURIOUS and ACK. Press **M** to mute.

This is a standalone visual prototype. Its records are explicitly illustrative; it does not invoke Terraform, Cedar, Ollama or the application API. Your existing application remains separate.

No installation is needed to open the HTML. An internet connection is needed for the permitted Three.js r128 CDN scripts and Google Fonts. WebGL failure falls back to readable content.

For a local HTTP preview, from the project root:

```powershell
python -m http.server 8011 --bind 127.0.0.1 --directory design
```

Then visit http://127.0.0.1:8011/planbound.html.

`DELIVERABLE.md` contains the entire HTML in one fenced code block. `SELF_REVIEW.md` contains the 17 acceptance results and remaining limitations. Screenshots and machine-readable test results are in `evidence/`.

The `planbound/` directory contains assembly sources and browser verification scripts. It is not needed to run the delivered HTML. Rebuilding uses the supplied editorial HTML in Downloads as the base. Verification scripts use Python Playwright and the installed Windows Chrome executable.
