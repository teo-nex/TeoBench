"""Resolve public OCI image tags to verified Linux amd64 manifest digests."""
import hashlib
import json
import re
from urllib.parse import quote
import urllib.request

ACCEPT=', '.join(['application/vnd.oci.image.index.v1+json','application/vnd.oci.image.manifest.v1+json',
                 'application/vnd.docker.distribution.manifest.list.v2+json','application/vnd.docker.distribution.manifest.v2+json'])


def resolve(image):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_./-]*:[a-zA-Z0-9_.-]+',image):
        raise ValueError('explicit_public_registry_tag_required')
    if image.startswith('ghcr.io/'):
        registry='ghcr.io';repo,tag=image[8:].rsplit(':',1)
        auth='https://ghcr.io/token?service=ghcr.io&scope='
    else:
        registry='registry-1.docker.io';repo,tag=image.rsplit(':',1)
        if '/' not in repo:repo='library/'+repo
        auth='https://auth.docker.io/token?service=registry.docker.io&scope='
    def get(url,headers=None):
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers or {}),timeout=45) as response:
            data=response.read(4_000_001)
        if len(data)>4_000_000:raise ValueError('registry_metadata_size_limit')
        return data
    token=json.loads(get(auth+quote('repository:'+repo+':pull')))['token']
    headers={'Authorization':'Bearer '+token,'Accept':ACCEPT,'Accept-Encoding':'identity'}
    data=get('https://'+registry+'/v2/'+repo+'/manifests/'+tag,headers)
    tag_digest='sha256:'+hashlib.sha256(data).hexdigest();manifest=json.loads(data)
    selected=tag_digest
    if 'manifests' in manifest:
        matches=[m for m in manifest['manifests'] if m.get('platform',{}).get('architecture')=='amd64'
                 and m.get('platform',{}).get('os')=='linux']
        if len(matches)!=1:raise ValueError('unique_linux_amd64_manifest_required')
        selected=matches[0]['digest']
        data=get('https://'+registry+'/v2/'+repo+'/manifests/'+selected,headers)
        if selected!='sha256:'+hashlib.sha256(data).hexdigest():raise ValueError('registry_manifest_hash_mismatch')
        manifest=json.loads(data)
    return {'image':image,'immutable_image':image.rsplit(':',1)[0]+'@'+selected,
            'platform_manifest_digest':selected,'tag_digest':tag_digest,'platform':'linux/amd64',
            'compressed_layer_bytes':sum(v['size'] for v in manifest['layers']),
            'layers':[{'digest':v['digest'],'size':v['size']} for v in manifest['layers']]}
