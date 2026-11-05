import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {checkpointFile} from '../teobench/medium_atomic.mjs';
test('transient Windows reader lock retries only the local checkpoint',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'medium-checkpoint-'));
 try{
  const file=path.join(dir,'receipt.json');let calls=0;
  checkpointFile(file,{requests:1},(a,b)=>{
   if(++calls<4){const error=new Error('reader holds file');error.code='EPERM';throw error;}
   fs.renameSync(a,b);
  });
  assert.equal(calls,4);assert.deepEqual(JSON.parse(fs.readFileSync(file)),{requests:1});
  const denied=()=>{const error=new Error('no space');error.code='ENOSPC';throw error;};
  assert.throws(()=>checkpointFile(file,{requests:2},denied),{code:'ENOSPC'});
  assert.deepEqual(JSON.parse(fs.readFileSync(file)),{requests:1});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
