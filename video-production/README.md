# Demo film

`renders/PlanReview-final-demo.mp4` (1920x1080, about 2:28, one female narrator, burned-in captions; `audio/captions.srt` is also included).

Rebuild (start the site first with `python run_site.py`):

```powershell
.\.venv\Scripts\python.exe -m pip install edge-tts pillow imageio-ffmpeg playwright
.\.venv\Scripts\python.exe video-production\src\capture.py        # real footage + screenshots -> assets/
.\.venv\Scripts\python.exe video-production\src\narration.py      # voice (en-US-AvaNeural) -> audio/
.\.venv\Scripts\python.exe video-production\src\render_scenes.py  # problem, architecture and AWS motion scenes
.\.venv\Scripts\python.exe video-production\src\build.py          # assemble, mix, caption -> renders/
```

Robot, globe and product footage are recordings of the running site. Problem, architecture and AWS scenes are HTML (`src/scenes.html`) recorded with Playwright. Ambient bed is synthesized with FFmpeg.
