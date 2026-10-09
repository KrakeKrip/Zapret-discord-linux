"""Run regression tests and expose failure details in GitHub check annotations."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
print(result.stdout, end='')
if result.returncode:
    start = result.stdout.find('======================================================================')
    details = result.stdout[start:] if start >= 0 else result.stdout[-8000:]
    escaped = details.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print(f'::error title=Regression failed::{escaped}')
raise SystemExit(result.returncode)
