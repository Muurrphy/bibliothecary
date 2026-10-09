"""Opt-in macOS login startup using an existing, user-owned launcher.

No dependency install, credential copying or provider changes at startup.
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = 'org.bibliothecary.librarian'


def configuration(launcher, log_dir):
    launcher = Path(launcher).expanduser().resolve()
    if not launcher.is_file():
        raise ValueError('Choose an existing launcher script')
    return {'Label':LABEL, 'ProgramArguments':['/bin/zsh',str(launcher)],
            'WorkingDirectory':str(launcher.parent), 'RunAtLoad':True,
            'KeepAlive':{'SuccessfulExit':False}, 'ThrottleInterval':60,
            'StandardOutPath':str(log_dir/'startup.log'), 'StandardErrorPath':str(log_dir/'startup-error.log')}


def command(args):
    if sys.platform != 'darwin': raise SystemExit('Login startup currently supports macOS only')
    destination = Path.home()/'Library'/'LaunchAgents'/f'{LABEL}.plist'
    domain=f'gui/{os.getuid()}'
    if args.action == 'status':
        return subprocess.run(['launchctl','print',f'{domain}/{LABEL}']).returncode
    if args.action == 'disable':
        subprocess.run(['launchctl','bootout',f'{domain}/{LABEL}'],check=False)
        if destination.exists(): destination.rename(destination.with_suffix('.disabled'))
        return 0
    if not args.launcher: raise SystemExit('--launcher is required for enable/write')
    log_dir=Path.home()/'Library'/'Logs'/'Bibliothecary'
    config=configuration(args.launcher,log_dir)
    destination.parent.mkdir(parents=True,exist_ok=True);log_dir.mkdir(parents=True,exist_ok=True)
    from .safe import atomic
    atomic(destination,plistlib.dumps(config).decode())
    if args.action == 'enable':
        return subprocess.run(['launchctl','bootstrap',domain,str(destination)]).returncode
    print(destination)
    return 0
