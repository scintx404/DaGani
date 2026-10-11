import {lex,activeAnimation,SPRITE_INDEX_STRING} from "./env.js";
import {applyOpsPlain,OpError} from "./ops.js";
export {OpError};
const dirs=a=>a.singleDir?1:4;
function pieces(f,d){return(f.pieces?.[d]||[]).filter(p=>p&&p.type!=="sound");}
function sprite(p){return p.spriteIndex===SPRITE_INDEX_STRING?p.spriteName:p.spriteIndex;}
export function toPlain(a){return{singleDir:!!a.singleDir,spriteIds:new Set([...a.sprites.keys()].map(Number)),frames:a.frames.map(f=>({duration:f.duration,sounds:(f.sounds||[]).map(s=>({file:s.fileName,x:s.xoffset,y:s.yoffset})),dirs:Array.from({length:dirs(a)},(_,d)=>pieces(f,d).map(p=>({sprite:sprite(p),x:p.xoffset,y:p.yoffset}))) }))};}
function refresh(){const f=lex("redraw");if(typeof f==="function")try{f();}catch{} }
function capture(a){return{frames:structuredClone(a.frames),sprites:a.sprites,defaults:a.defaultImages,looped:a.looped,singleDir:a.singleDir,continous:a.continous,nextAni:a.nextAni};}
function restore(a,s){a.frames=s.frames;a.sprites=s.sprites;a.defaultImages=s.defaults;a.looped=s.looped;a.singleDir=s.singleDir;a.continous=s.continous;a.nextAni=s.nextAni;}
export class EditorAdapter{
 constructor({undo=null}={}){this.rev=0;this.tx=null;this.undo=undo;this.last=null;}
 current(){const x=activeAnimation();if(!x)throw new OpError("no gani tab is open");return x;}
 snapshot(){const {ani}=this.current();const nd=dirs(ani);return{rev:this.rev,file:ani.fileName||"",options:{LOOP:!!ani.looped,CONTINUOUS:!!ani.continous,SINGLEDIRECTION:!!ani.singleDir,SETBACKTO:ani.nextAni||null},defaults:Object.fromEntries(ani.defaultImages||[]),sprites:[...ani.sprites.values()].map(s=>({index:s.index,source:s.type,left:s.left,top:s.top,width:s.width,height:s.height,comment:s.comment||""})),frames:ani.frames.map(f=>({duration:f.duration,sounds:(f.sounds||[]).map(s=>({file:s.fileName,x:s.xoffset,y:s.yoffset})),dirs:Array.from({length:nd},(_,d)=>pieces(f,d).map(p=>({sprite:sprite(p),x:p.xoffset,y:p.yoffset}))) }))};}
 applyOps(ops,{baseRev,label="AI edit"}={}){if(baseRev!=null&&baseRev!==this.rev){const e=new OpError("state changed since snapshot");e.code=-32010;throw e;}const {ani}=this.current(),before=this.tx?null:capture(ani),old=toPlain(ani),next=applyOpsPlain(old,ops);ani.frames=next.frames.map((f,i)=>{const o=ani.frames[i]||new (lex("Frame"))();o.duration=f.duration;o.pieces=f.dirs.map(d=>d.map(p=>{const q=new (lex("FramePieceSprite"))();q.spriteIndex=typeof p.sprite==="number"?p.sprite:SPRITE_INDEX_STRING;q.spriteName=String(p.sprite);q.xoffset=p.x;q.yoffset=p.y;return q;}));o.sounds=f.sounds.map(s=>{const q=new (lex("FramePieceSound"))();q.fileName=s.file;q.xoffset=s.x;q.yoffset=s.y;return q;});return o;});ani.modified=true;this.rev++;refresh();if(before&&this.undo)this.undo(ani,label,before,capture(ani));return{rev:this.rev,applied:ops.length};}
 load(text){const p=globalThis.parseGani?.(text);if(!p)throw new OpError("editor failed to parse proposal");const {ani}=this.current();if(!this.tx)this.before=capture(ani);Object.assign(ani,p);ani.modified=true;this.rev++;refresh();return{rev:this.rev};}
 txBegin(label="AI edit"){if(this.tx)throw new OpError("a transaction is already open");const {ani}=this.current();this.tx={id:"tx_"+Math.random().toString(36).slice(2,8),ani,before:capture(ani),label};return{txId:this.tx.id};}
 txCommit(id){if(!this.tx||id&&this.tx.id!==id)throw new OpError("unknown transaction");const t=this.tx;this.tx=null;if(this.undo)this.undo(t.ani,t.label,t.before,capture(t.ani));return{ok:true,rev:this.rev};}
 txRollback(id){if(!this.tx||id&&this.tx.id!==id)throw new OpError("unknown transaction");const t=this.tx;restore(t.ani,t.before);this.tx=null;this.rev++;refresh();return{ok:true,rev:this.rev};}
 pollUserChange(){const f=JSON.stringify(this.snapshot(),(_,v)=>v&&v.rev===this.rev?undefined:v);if(this.last===null){this.last=f;return null;}if(f!==this.last){this.last=f;this.rev++;return"edit";}return null;}
}
