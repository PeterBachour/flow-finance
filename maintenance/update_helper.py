#!/usr/bin/env python3
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(os.environ.get('FLOW_REPO_ROOT', '')).resolve()
APP = REPO
HELPER = Path(__file__).resolve()
HELPER_MTIME = HELPER.stat().st_mtime_ns
MAINTENANCE = Path(os.getenv('FLOW_MAINTENANCE_DIR', '/var/lib/flow-finance-maintenance'))
STATUS = MAINTENANCE / 'status.json'
REQUEST = MAINTENANCE / 'request'
CHECK_REQUEST = MAINTENANCE / 'check-request'
LOCK = MAINTENANCE / 'update.lock'
POLL_SECONDS = 2
GIT_TIMEOUT = 120
BUILD_TIMEOUT = 1800
TEST_TIMEOUT = 1800
RUNTIME_TIMEOUT = 90


def run(*args, cwd=REPO, timeout=GIT_TIMEOUT, env=None):
    result = subprocess.run(args, cwd=cwd, check=False, text=True, capture_output=True, timeout=timeout, env=env)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        raise RuntimeError(f"{' '.join(args)}: {detail or f'exit {result.returncode}'}")
    return result.stdout.strip()


def write(state, message, current='', remote='', **extra):
    MAINTENANCE.mkdir(parents=True, exist_ok=True)
    payload = {
        'state': state,
        'message': message,
        'current_commit': current,
        'remote_commit': remote,
        'updated_at': int(time.time()),
        **extra,
    }
    tmp = STATUS.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.replace(STATUS)


def prerequisites():
    errors = []
    if not REPO or not (REPO / '.git').exists():
        errors.append(f'Repo Git introuvable: {REPO}')
    if not APP.exists():
        errors.append(f'Dossier Flow introuvable: {APP}')
    if not (APP / 'docker-compose.yml').is_file():
        errors.append('docker-compose.yml introuvable')
    if shutil.which('git') is None:
        errors.append('git introuvable')
    if shutil.which('docker') is None:
        errors.append('docker introuvable')
    if errors:
        raise RuntimeError(' ; '.join(errors))
    run('docker', 'compose', 'version', cwd=APP, timeout=30)


def dirty_paths():
    out = run('git', 'status', '--porcelain', '--untracked-files=all')
    return [line[3:] if len(line) > 3 else line for line in out.splitlines() if line.strip()]


def commits(fetch=True):
    current = run('git', 'rev-parse', 'HEAD')
    if fetch:
        run('git', 'fetch', '--prune', 'origin', 'main')
    remote = run('git', 'rev-parse', 'origin/main')
    return current, remote


def version_for_ref(ref):
    try:
        text = run('git', 'show', f'{ref}:app/version.py', timeout=30)
        match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
        return match.group(1) if match else ''
    except Exception:
        return ''


def relation(current, remote):
    if current == remote:
        return 'up_to_date'
    remote_contains_local = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', current, remote], cwd=REPO, check=False, capture_output=True, timeout=30
    ).returncode == 0
    local_contains_remote = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', remote, current], cwd=REPO, check=False, capture_output=True, timeout=30
    ).returncode == 0
    if remote_contains_local:
        return 'fast_forward'
    if local_contains_remote:
        return 'local_ahead'
    return 'diverged'


def validate_python_ref(ref):
    files = run('git', 'ls-tree', '-r', '--name-only', ref, 'app', timeout=60).splitlines()
    checked = 0
    for path in files:
        if not path.endswith('.py'):
            continue
        source = run('git', 'show', f'{ref}:{path}', timeout=30)
        try:
            compile(source, path, 'exec')
        except SyntaxError as exc:
            line = exc.lineno or '?'
            raise RuntimeError(f'Erreur de syntaxe dans {path}:{line}: {exc.msg}') from exc
        checked += 1
    if checked == 0:
        raise RuntimeError('Aucun fichier Python Flow trouvé pour le contrôle préflight')
    return checked


def inspect_remote():
    prerequisites()
    dirty = dirty_paths()
    current, remote = commits(fetch=True)
    rel = relation(current, remote)
    versions = {'local_version': version_for_ref('HEAD'), 'remote_version': version_for_ref('origin/main')}
    return current, remote, rel, dirty, versions


def check():
    try:
        write('checking', 'Vérification de origin/main…')
        current, remote, rel, dirty, versions = inspect_remote()
        if dirty:
            write('blocked', 'Mise à jour bloquée: dépôt local modifié', current, remote, dirty=True, dirty_paths=dirty, relation=rel, **versions)
        elif rel == 'up_to_date':
            write('idle', 'Flow est à jour', current, remote, relation=rel, **versions)
        elif rel == 'fast_forward':
            try:
                checked = validate_python_ref('origin/main')
            except Exception as exc:
                write('blocked', f'Mise à jour bloquée par le préflight: {exc}', current, remote, relation=rel, preflight='failed', **versions)
                return
            write('available', 'Une mise à jour validée est disponible', current, remote, relation=rel, preflight='passed', python_files_checked=checked, **versions)
        elif rel == 'local_ahead':
            write('blocked', 'Mise à jour bloquée: le dépôt local contient des commits absents de origin/main', current, remote, relation=rel, **versions)
        else:
            write('blocked', 'Mise à jour bloquée: divergence Git détectée', current, remote, relation=rel, **versions)
    except Exception as exc:
        write('error', f'Échec de la vérification: {exc}', error=str(exc))


def reload_helper_if_changed():
    try:
        if HELPER.stat().st_mtime_ns != HELPER_MTIME:
            os.execv(sys.executable, [sys.executable, str(HELPER)])
    except OSError:
        pass


def current_container_image():
    try:
        image_id = run('docker', 'inspect', '--format', '{{.Image}}', 'flow-finance', cwd=APP, timeout=30)
        image_name = run('docker', 'inspect', '--format', '{{.Config.Image}}', 'flow-finance', cwd=APP, timeout=30)
        return image_id, image_name
    except Exception:
        return '', ''


def test_built_image(image_id):
    if not image_id:
        raise RuntimeError('Image Docker construite introuvable')
    output = run(
        'docker', 'run', '--rm', '--entrypoint', 'pytest',
        image_id, '-q',
        cwd=APP, timeout=TEST_TIMEOUT,
    )
    if 'failed' in output.lower():
        raise RuntimeError(f'Tests Flow en échec: {output.splitlines()[-1]}')
    return output.splitlines()[-1] if output else 'pytest terminé'


def smoke_built_image(image_id):
    if not image_id:
        raise RuntimeError('Image Docker construite introuvable')
    run(
        'docker', 'run', '--rm', '--entrypoint', 'python',
        '-e', 'FLOW_DB_PATH=/tmp/flow-smoke.db',
        '-e', 'FLOW_UPDATE_ENABLED=0',
        image_id,
        '-c', 'import app.main; assert app.main.app.title == "Flow Finance"; print("startup-import-ok")',
        cwd=APP, timeout=120,
    )


def http_json(path, timeout=5):
    with urllib.request.urlopen(f'http://127.0.0.1:8010{path}', timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f'{path}: HTTP {response.status}')
        return json.loads(response.read().decode('utf-8'))


def wait_for_runtime(expected_version, timeout=RUNTIME_TIMEOUT):
    deadline = time.time() + timeout
    last_error = 'service indisponible'
    while time.time() < deadline:
        try:
            health = http_json('/api/health')
            version = http_json('/api/version')
            system = http_json('/api/v3/system')
            if health.get('status') != 'ok':
                raise RuntimeError('healthcheck applicatif KO')
            if version.get('version') != expected_version:
                raise RuntimeError(f"version active {version.get('version')} != {expected_version}")
            if system.get('version') != expected_version:
                raise RuntimeError('System Center ne remonte pas la version attendue')
            return {'health': health, 'version': version, 'system': system}
        except Exception as exc:
            last_error = str(exc)
            time.sleep(3)
    raise RuntimeError(f'Flow ne passe pas les smoke tests après {timeout}s: {last_error}')


def rollback_runtime(previous_image_id, previous_image_name, previous_commit, previous_version):
    if not previous_image_id or not previous_image_name:
        raise RuntimeError('Rollback automatique impossible: image précédente inconnue')
    rollback_env = os.environ.copy()
    rollback_env['FLOW_GIT_COMMIT'] = previous_commit
    run('docker', 'tag', previous_image_id, previous_image_name, cwd=APP, timeout=60)
    run('docker', 'compose', 'up', '-d', '--no-deps', '--force-recreate', 'flow-finance', cwd=APP, timeout=300, env=rollback_env)
    wait_for_runtime(previous_version, timeout=RUNTIME_TIMEOUT)


def update_locked():
    current, remote, rel, dirty, versions = inspect_remote()
    if dirty:
        write('blocked', 'Mise à jour refusée: dépôt local modifié', current, remote, dirty=True, dirty_paths=dirty, relation=rel, **versions)
        return
    if rel == 'up_to_date':
        write('idle', 'Flow est déjà à jour', current, remote, relation=rel, **versions)
        return
    if rel != 'fast_forward':
        write('blocked', 'Mise à jour refusée: fast-forward impossible', current, remote, relation=rel, **versions)
        return

    try:
        checked = validate_python_ref('origin/main')
    except Exception as exc:
        write('blocked', f'Mise à jour refusée par le préflight: {exc}', current, remote, relation=rel, preflight='failed', **versions)
        return

    previous_image_id, previous_image_name = current_container_image()
    previous_version = versions.get('local_version') or ''

    write('downloading', 'Téléchargement de la mise à jour…', current, remote, relation=rel, preflight='passed', python_files_checked=checked, **versions)
    run('git', 'merge', '--ff-only', 'origin/main')
    new_commit = run('git', 'rev-parse', 'HEAD')
    new_version = version_for_ref('HEAD')

    env = os.environ.copy()
    env['FLOW_GIT_COMMIT'] = new_commit
    write('building', 'Reconstruction et validation du conteneur Flow…', new_commit, new_commit, relation='up_to_date', local_version=new_version, remote_version=new_version)
    run('docker', 'compose', 'build', 'flow-finance', cwd=APP, timeout=BUILD_TIMEOUT, env=env)
    image_id = run('docker', 'compose', 'images', '-q', 'flow-finance', cwd=APP, timeout=60, env=env).splitlines()[0].strip()

    write('testing', 'Exécution de la recette complète Flow…', new_commit, new_commit, relation='up_to_date', local_version=new_version, remote_version=new_version)
    test_summary = test_built_image(image_id)
    smoke_built_image(image_id)

    write('restarting', 'Redémarrage et smoke tests Flow…', new_commit, new_commit, relation='up_to_date', local_version=new_version, remote_version=new_version, tests='passed', test_summary=test_summary)
    run('docker', 'compose', 'up', '-d', '--no-deps', 'flow-finance', cwd=APP, timeout=300, env=env)

    try:
        wait_for_runtime(new_version)
    except Exception as exc:
        try:
            rollback_runtime(previous_image_id, previous_image_name, current, previous_version)
            write(
                'error',
                f'Nouvelle version invalide, ancienne version restaurée automatiquement: {exc}',
                new_commit, new_commit, relation='up_to_date', local_version=new_version, remote_version=new_version,
                runtime='rolled_back', rollback_version=previous_version, error=str(exc),
            )
        except Exception as rollback_exc:
            write(
                'error',
                f'Échec runtime et rollback automatique impossible: {exc} ; rollback: {rollback_exc}',
                new_commit, new_commit, relation='up_to_date', local_version=new_version, remote_version=new_version,
                runtime='failed', error=str(exc), rollback_error=str(rollback_exc),
            )
        return

    write('completed', 'Mise à jour terminée et validée', new_commit, new_commit, relation='up_to_date', local_version=new_version, remote_version=new_version, runtime='healthy', tests='passed', test_summary=test_summary)
    reload_helper_if_changed()


def update():
    MAINTENANCE.mkdir(parents=True, exist_ok=True)
    try:
        with LOCK.open('w') as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                write('blocked', 'Une autre mise à jour est déjà en cours')
                return
            update_locked()
    except Exception as exc:
        current = ''
        remote = ''
        try:
            current, remote = commits(fetch=False)
        except Exception:
            pass
        write('error', f'Échec de la mise à jour: {exc}', current, remote, error=str(exc))


def main():
    MAINTENANCE.mkdir(parents=True, exist_ok=True)
    if not STATUS.exists():
        check()
    while True:
        if CHECK_REQUEST.exists():
            CHECK_REQUEST.unlink(missing_ok=True)
            check()
        if REQUEST.exists():
            REQUEST.unlink(missing_ok=True)
            update()
        reload_helper_if_changed()
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
