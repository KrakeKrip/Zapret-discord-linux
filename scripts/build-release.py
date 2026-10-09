"""Build Python distributions and a complete tracked-source Linux archive."""
import ast
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def version():
    project = (ROOT / 'pyproject.toml').read_text()
    number = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', project, re.M).group(1)
    declarations = ast.parse((ROOT / 'src/zapret_console/__init__.py').read_text())
    actual = next(ast.literal_eval(node.value) for node in declarations.body
                  if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets))
    if number != actual:
        raise RuntimeError('Version mismatch between pyproject.toml and __init__.py')
    return number


def main():
    number = version()
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], cwd=ROOT).returncode != 0:
        raise RuntimeError('Commit tracked changes before building the HEAD source archive')
    dist = ROOT / 'dist'
    if dist.exists() and any(dist.iterdir()):
        raise RuntimeError('dist is not empty; use a clean build directory before release')
    dist.mkdir(exist_ok=True)
    archive = dist / f'zapret-manager-{number}-linux.tar.gz'
    subprocess.run(['git', 'archive', '--format=tar.gz', f'--prefix=zapret-manager-{number}/',
                    f'--output={archive}', 'HEAD'], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='zapret-release-') as folder:
        subprocess.run(['tar', '-xzf', str(archive), '-C', folder], check=True)
        source = Path(folder) / f'zapret-manager-{number}'
        subprocess.run([sys.executable, '-I', '-m', 'build', '--outdir', str(dist), str(source)], check=True)
    files = sorted(path for path in dist.iterdir() if path.is_file())
    (dist / 'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in files))
    print(f'Built Zapret Manager {number}: {dist}')


if __name__ == '__main__':
    main()
