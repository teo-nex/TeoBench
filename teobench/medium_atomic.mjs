// Windows readers and virus scanners can briefly hold a destination without
// FILE_SHARE_DELETE. Retry only that transient rename, never a model request.
import fs from 'node:fs';
export function checkpointFile(path,value,rename=fs.renameSync){
 fs.writeFileSync(path+'.tmp',JSON.stringify(value),{mode:0o600,flush:true});
 const wait=new Int32Array(new SharedArrayBuffer(4));
 for(let attempt=0;;attempt++){
  try{rename(path+'.tmp',path);return;}
  catch(error){
   if(!['EPERM','EACCES','EBUSY'].includes(error.code)||attempt>=29)throw error;
   Atomics.wait(wait,0,0,40);
  }
 }
}
