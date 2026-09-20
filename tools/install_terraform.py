"""Build-time helper for hosted deploys (Render): download the Terraform CLI into ./bin and warm the AWS provider cache.
Usage: python tools/install_terraform.py"""

import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = os.environ.get("TERRAFORM_VERSION", "1.9.8")


def main():
    system = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}[platform.system()]
    arch = {"x86_64": "amd64", "AMD64": "amd64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine()]
    url = f"https://releases.hashicorp.com/terraform/{VERSION}/terraform_{VERSION}_{system}_{arch}.zip"
    bindir = ROOT / "bin"
    bindir.mkdir(exist_ok=True)
    exe = bindir / ("terraform.exe" if system == "windows" else "terraform")
    if not exe.exists():
        print("Downloading", url)
        with zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url, timeout=120).read())) as z:
            exe.write_bytes(z.read(z.namelist()[0]))
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"], "TF_PLUGIN_CACHE_DIR": str(ROOT / ".provider-cache")}
    (ROOT / ".provider-cache").mkdir(exist_ok=True)
    work = ROOT / "data" / "_warm"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for n in ["main.tf", ".terraform.lock.hcl", "lambda.zip"]:
        s = ROOT / "terraform/fixtures/baseline" / n
        if s.exists():
            shutil.copy2(s, work / n)
    print("Warming the AWS provider cache (one-time download)...")
    r = subprocess.run([str(exe), "init", "-input=false", "-no-color"], cwd=work, env=env)
    shutil.rmtree(work, ignore_errors=True)
    sys.exit(r.returncode)


main()
