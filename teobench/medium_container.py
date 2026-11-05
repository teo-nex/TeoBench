"""Owned Linux task containers. No host mounts, published ports or broad pruning."""
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import uuid


class ContainerError(RuntimeError):
    pass


def safe_absolute(path):
    value = PurePosixPath(path)
    if (not value.is_absolute() or '..' in value.parts or '\\' in path
            or '\0' in path or ':' in path or len(path) > 1000):
        raise ValueError('invalid_container_path')
    return str(value)


class Docker:
    def __init__(self, *, executable=None, reserve_gib=12):
        self.executable = executable or shutil.which('docker')
        if not self.executable:
            raise ContainerError('installed_docker_required')
        self.reserve_bytes = int(reserve_gib * 1024**3)
        self.env = {k: v for k, v in os.environ.items() if k in {
            'PATH','HOME','USERPROFILE','APPDATA','LOCALAPPDATA','SystemRoot','SYSTEMROOT',
            'COMSPEC','PATHEXT','TEMP','TMP','DOCKER_HOST','DOCKER_CONTEXT'}}
        # Windows Desktop's interactive credential store is unavailable over
        # SSH. Public benchmark pulls must not read or modify personal registry
        # credentials. Preserve the existing engine endpoint in a private,
        # empty per-process config instead of changing the global context.
        _,raw=self.call(['context','inspect'])
        endpoint=json.loads(raw)[0]['Endpoints']['docker']['Host']
        if not endpoint.startswith(('npipe://','unix://')):
            raise ContainerError('existing_local_docker_engine_required')
        self._config=tempfile.TemporaryDirectory(prefix='teobench-docker-')
        # A completely empty auth map triggers Docker CLI's automatic native
        # credential-helper detection. An anonymous registry entry suppresses
        # that detection without supplying any username, password or token.
        (Path(self._config.name)/'config.json').write_text('{"auths":{"https://index.docker.io/v1/":{}}}')
        self.env.pop('DOCKER_CONTEXT',None)
        self.env['DOCKER_HOST']=endpoint
        self.env['DOCKER_CONFIG']=self._config.name

    def call(self, args, *, data=None, timeout=60, check=True, log=None):
        if log:
            with Path(log).open('wb') as output:
                result = subprocess.run([self.executable,*args],input=data,stdout=output,
                                        stderr=subprocess.STDOUT,timeout=timeout,env=self.env)
            content = b''
        else:
            result = subprocess.run([self.executable,*args],input=data,capture_output=True,
                                    timeout=timeout,env=self.env)
            content = result.stdout
        if check and result.returncode:
            raise ContainerError('docker_'+args[0]+'_failed')
        return result.returncode, content

    def inspect(self, image):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,400}', image):
            raise ValueError('invalid_image_reference')
        code, data = self.call(['image','inspect',image],check=False)
        if code:
            return None
        value = json.loads(data)[0]
        if value.get('Os') != 'linux' or value.get('Architecture') != 'amd64':
            raise ContainerError('linux_amd64_image_required')
        return value

    def pull(self, image, *, log, disk_path):
        if '@sha256:' not in image or not re.fullmatch(r'.+@sha256:[a-f0-9]{64}',image):
            raise ValueError('immutable_registry_digest_required')
        existing = self.inspect(image)
        if existing:
            return existing
        if shutil.disk_usage(disk_path).free < self.reserve_bytes:
            raise ContainerError('host_disk_reserve_reached')
        # Do not allow the Docker Desktop sparse disk to fill the Windows host.
        with Path(log).open('wb') as output:
            process = subprocess.Popen([self.executable,'pull','--platform','linux/amd64',image],
                stdout=output,stderr=subprocess.STDOUT,env=self.env)
            try:
                for _ in range(900):
                    try:
                        code=process.wait(timeout=2)
                        break
                    except subprocess.TimeoutExpired:
                        if shutil.disk_usage(disk_path).free < self.reserve_bytes:
                            raise ContainerError('host_disk_reserve_reached_during_pull')
                else:
                    raise ContainerError('image_pull_timeout')
                if code:
                    raise ContainerError('image_pull_failed')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
        if shutil.disk_usage(disk_path).free < self.reserve_bytes:
            raise ContainerError('host_disk_reserve_reached_after_unpack')
        return self.inspect(image)

    def read_file(self, container, path, *, limit=32_000_000):
        """Read a bounded regular file. Never extract candidate tar paths on host."""
        safe_absolute(path)
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen([self.executable,'cp',container+':'+path,'-'],
                stdout=subprocess.PIPE,stderr=errors,env=self.env)
            timer=threading.Timer(60,process.kill);timer.start()
            try:
                data=process.stdout.read(limit+65537)
                if len(data)>limit+65536:
                    process.kill()
                    raise ContainerError('artifact_size_limit')
                if process.wait(timeout=10):
                    raise ContainerError('artifact_missing_or_unreadable')
            finally:
                timer.cancel()
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close()
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
            members=archive.getmembers()
            if len(members)!=1 or not members[0].isfile() or members[0].size>limit:
                raise ContainerError('artifact_must_be_one_bounded_regular_file')
            member=members[0]
            if PurePosixPath(member.name).name != PurePosixPath(path).name:
                raise ContainerError('artifact_name_mismatch')
            return archive.extractfile(member).read(limit+1)


class TaskContainer:
    def __init__(self, docker, image, *, workdir='/app', memory_mb=2048, cpus=1,
                 network='none', environment=None, purpose='medium-task'):
        self.docker=docker;self.image=image;self.workdir=safe_absolute(workdir)
        self.memory_mb=memory_mb;self.cpus=cpus;self.network=network
        self.environment=environment or {};self.purpose=purpose
        self.id=None;self.owner='teobench-'+uuid.uuid4().hex

    def __enter__(self):
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',self.image):
            raise ValueError('immutable_local_image_id_required')
        if not 128<=self.memory_mb<=8192 or not 0<self.cpus<=4:
            raise ValueError('task_resource_budget_invalid')
        if self.network != 'none':
            if not re.fullmatch(r'teobench-net-[a-f0-9]{32}', self.network):
                raise ValueError('owned_internal_network_required')
            _, raw = self.docker.call(['network','inspect',self.network])
            network = json.loads(raw)[0]
            if (network.get('Internal') is not True or network.get('Labels',{}).get('org.teobench.owner') != self.network
                    or network.get('Options',{}).get('com.docker.network.bridge.gateway_mode_ipv4')!='isolated'):
                raise ContainerError('internal_network_ownership_mismatch')
        args=['run','--detach','--pull=never','--platform','linux/amd64','--name',self.owner,
              '--label','org.teobench.owner='+self.owner,'--label','org.teobench.kind='+self.purpose,
              '--network',self.network,'--security-opt=no-new-privileges','--cap-drop=ALL',
              '--pids-limit=1024','--memory='+str(self.memory_mb)+'m','--cpus='+str(self.cpus),
              '--workdir',self.workdir,'--entrypoint','/bin/sh']
        for cap in ('CHOWN','DAC_OVERRIDE','FOWNER','SETGID','SETUID'):
            args+=['--cap-add',cap]
        for key,value in self.environment.items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',key):
                raise ValueError('invalid_container_environment_key')
            args+=['--env',key+'='+str(value)]
        args += [self.image,'-c','while :; do sleep 3600; done']
        try:
            _,output=self.docker.call(args,timeout=180)
        except BaseException:
            # Creation can succeed in the daemon even if the client times out.
            # Find only our unpredictable, labelled name and remove only it.
            code,raw=self.docker.call(['inspect','--format','{{json .Config.Labels}}',self.owner],check=False)
            if not code and json.loads(raw).get('org.teobench.owner')==self.owner:
                self.docker.call(['rm','--force',self.owner],timeout=180)
            raise
        self.id=output.decode().strip()
        if not re.fullmatch(r'[a-f0-9]{64}',self.id):
            raise ContainerError('invalid_container_receipt')
        return self

    def exec(self, command, *, timeout=60, check=True, log=None):
        return self.docker.call(['exec','--workdir',self.workdir,self.id,'/bin/bash','-lc',command],
                                timeout=timeout,check=check,log=log)

    def put(self, source, target):
        safe_absolute(target)
        self.docker.call(['cp',str(Path(source).resolve()),self.id+':'+target],timeout=600)

    def read(self, path, *, limit=32_000_000):
        return self.docker.read_file(self.id,path,limit=limit)

    def __exit__(self,*_):
        if self.id:
            _,raw=self.docker.call(['inspect','--format','{{json .Config.Labels}}',self.id])
            if json.loads(raw).get('org.teobench.owner')!=self.owner:
                raise ContainerError('container_ownership_mismatch_no_deletion')
            self.docker.call(['rm','--force',self.id])


class PublicEgress:
    """Owned internal network: tasks can reach public HTTP(S) only via proxy.

    The external bridge is attached to the credential-free proxy, never a task.
    No host ports, firewall rules, routes or existing containers are changed.
    """
    def __init__(self, docker, proxy_image):
        self.docker=docker;self.proxy_image=proxy_image
        self.name='teobench-net-'+uuid.uuid4().hex
        self.proxy=None

    def __enter__(self):
        self.docker.call(['network','create','--internal','--opt',
                         'com.docker.network.bridge.gateway_mode_ipv4=isolated','--label',
                         'org.teobench.owner='+self.name,self.name])
        try:
            self.proxy=TaskContainer(self.docker,self.proxy_image,workdir='/tmp',
                memory_mb=128,cpus=.25,network=self.name,purpose='public-egress')
            self.proxy.__enter__()
            self.proxy.put(Path(__file__).with_name('medium_egress.py'),'/tmp/proxy.py')
            self.docker.call(['network','connect','bridge',self.proxy.id])
            self.docker.call(['exec','--detach',self.proxy.id,'python3','/tmp/proxy.py'])
            self.proxy.exec("python3 -c \"import socket,time;\nfor _ in range(50):\n try: socket.create_connection(('127.0.0.1',3128),.2).close(); break\n except OSError: time.sleep(.1)\nelse: raise SystemExit(1)\"",timeout=10)
            return self
        except BaseException:
            self.__exit__()
            raise

    @property
    def environment(self):
        url='http://'+self.proxy.owner+':3128'
        return {'HTTP_PROXY':url,'HTTPS_PROXY':url,'http_proxy':url,'https_proxy':url,
                'NO_PROXY':'localhost,127.0.0.1,::1','no_proxy':'localhost,127.0.0.1,::1'}

    def __exit__(self,*_):
        if self.proxy and self.proxy.id:
            self.proxy.__exit__();self.proxy.id=None
        code,raw=self.docker.call(['network','inspect',self.name],check=False)
        if not code:
            if json.loads(raw)[0].get('Labels',{}).get('org.teobench.owner')!=self.name:
                raise ContainerError('network_ownership_mismatch_no_deletion')
            self.docker.call(['network','rm',self.name])
