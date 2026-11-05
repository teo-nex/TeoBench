"""Explicit Windows Pi installation using native Node/npm, without PowerShell scripts.

No client is installed unless --install is requested. No model requests,
sign-in, engine setup, profile edits or network/security setting changes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

VERSION = '0.85.1'
PACKAGE = '@earendil-works/pi-coding-agent'


def node_environment(source=None):
    source=os.environ if source is None else source
    allowed={'PATH','HOME','USERPROFILE','APPDATA','LOCALAPPDATA','SystemRoot','SYSTEMROOT',
             'COMSPEC','PATHEXT','TMP','TEMP','TMPDIR','LANG','LC_ALL','HTTPS_PROXY','HTTP_PROXY',
             'ALL_PROXY','NO_PROXY','https_proxy','http_proxy','all_proxy','no_proxy',
             'SSL_CERT_FILE','SSL_CERT_DIR','NODE_EXTRA_CA_CERTS'}
    return {k:v for k,v in source.items() if k in allowed}


def native(args,logs,name,env):
    """stderr warnings are log data; only the native exit status means failure."""
    with (logs/(name+'.stdout.log')).open('w',encoding='utf-8') as out, \
         (logs/(name+'.stderr.log')).open('w',encoding='utf-8') as err:
        result=subprocess.run(args,stdout=out,stderr=err,env=env,timeout=300)
    if result.returncode:
        raise ValueError('BLOCKED: '+name+' failed with exit '+str(result.returncode)+'; see setup logs')
    return (logs/(name+'.stdout.log')).read_text(encoding='utf-8',errors='replace').strip()


def setup(*,install=False,prefix=None,replace_existing_version=False):
    if replace_existing_version and not install:
        raise ValueError('replacement_requires_explicit_install')
    node=shutil.which('node')
    if not node:raise ValueError('BLOCKED: installed Node.js 22.19+ required; no automatic Node installation')
    if prefix is None:
        prefix=Path(os.environ['APPDATA'])/'npm' if os.name=='nt' else Path.home()/'.local'
    prefix=Path(prefix).expanduser().resolve()
    package=prefix/'node_modules/@earendil-works/pi-coding-agent'
    metadata=package/'package.json'
    data=json.loads(metadata.read_text(encoding='utf-8')) if metadata.is_file() else None
    if data and data.get('version')!=VERSION and not replace_existing_version:
        raise ValueError('BLOCKED: different installed Pi version; preserve it or explicitly request replacement')
    if data and data.get('name')!=PACKAGE:
        raise ValueError('BLOCKED: unexpected installed package identity')
    needs_install=not data or data.get('version')!=VERSION or not (package/'dist/index.js').is_file()
    if needs_install and not install:
        raise ValueError('BLOCKED: Pi missing; explicit --install authorization required')
    logs=Path(tempfile.mkdtemp(prefix='teobench-pi-setup-'));logs.chmod(0o700)
    env=node_environment()
    version=native([node,'--version'],logs,'node-version',env)
    match=re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)',version)
    if not match or tuple(map(int,match.groups()))<(22,19,0):
        raise ValueError('BLOCKED: installed Node.js 22.19+ required')
    if needs_install:
        if os.name!='nt':raise ValueError('BLOCKED: this install helper targets Windows npm prefixes')
        # npm.cmd is a PowerShell/cmd wrapper. Invoke its native JS CLI through
        # node.exe instead, so no script execution policy needs to change.
        npm=Path(node).parent/'node_modules/npm/bin/npm-cli.js'
        if not npm.is_file():
            executable=shutil.which('npm')
            npm=Path(executable).resolve() if executable and os.name!='nt' else npm
        if not npm.is_file():raise ValueError('BLOCKED: native npm CLI missing')
        empty=logs/'empty.npmrc';empty.write_text('',encoding='utf-8')
        env['NPM_CONFIG_USERCONFIG']=str(empty)
        native([node,str(npm),'install','--global','--prefix',str(prefix),
                '--registry=https://registry.npmjs.org','--ignore-scripts','--no-audit','--no-fund',
                PACKAGE+'@'+VERSION],logs,'install',env)
    data=json.loads(metadata.read_text(encoding='utf-8'))
    if data.get('name')!=PACKAGE or data.get('version')!=VERSION:
        raise ValueError('BLOCKED: installed Pi identity/version mismatch')
    actual=native([node,str(package/'dist/bundle/cli.js'),'--version'],logs,'pi-version',env)
    if actual!=VERSION:raise ValueError('BLOCKED: Pi startup/version check failed')
    return {'status':'PI_READY','pi_version':actual,'node_version':version,'package':str(package),
            'launcher_on_path':bool(shutil.which('pi')),'installed_this_run':needs_install,
            'personal_profile_changed':False,'security_settings_changed':False,'logs':str(logs)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true',help='explicitly install pinned Pi if missing')
    parser.add_argument('--prefix',type=Path,help='user-owned npm prefix; no PATH is modified')
    parser.add_argument('--replace-existing-version',action='store_true')
    args=parser.parse_args()
    try:result=setup(install=args.install,prefix=args.prefix,replace_existing_version=args.replace_existing_version)
    except (ValueError,OSError,subprocess.TimeoutExpired) as error:
        print(json.dumps({'status':'BLOCKED','error':str(error)}));raise SystemExit(2)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
