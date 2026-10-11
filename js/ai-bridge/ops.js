export const DIRS = ["up", "left", "down", "right"];
export const TICK_MS = 50;
export class OpError extends Error {}
export function msToDuration(ms) { return Math.max(1, Math.round(Number(ms) / TICK_MS)) * TICK_MS; }
function dirIndex(doc, d) { if (doc.singleDir) return 0; if (Number.isInteger(d)) return d; const i = DIRS.indexOf(d); if (i < 0) throw new OpError(`unknown dir ${d}`); return i; }
function frameAt(doc, i) { if (!doc.frames[i]) throw new OpError(`frame ${i} does not exist`); return doc.frames[i]; }
function layerOf(doc, op) { const fr = frameAt(doc, op.frame), pieces = fr.dirs[dirIndex(doc, op.dir)], li = op.layer ?? 0; if (!pieces || li < 0 || li >= pieces.length) throw new OpError(`layer ${li} does not exist`); return { fr, pieces, li }; }
const n = v => { const x = Number(v); if (!Number.isFinite(x)) throw new OpError(`not a number: ${v}`); return Math.trunc(x); };
function clone(doc) { return { singleDir: doc.singleDir, spriteIds: doc.spriteIds, frames: doc.frames.map(f => ({ _ref:f._ref, duration:f.duration, sounds:f.sounds.map(s=>({...s})), dirs:f.dirs.map(d=>d.map(p=>({...p}))) })) }; }
function one(doc, op, ids) { switch (op.op) {
  case "move": { const {pieces,li}=layerOf(doc,op); pieces[li].x=n(op.x); pieces[li].y=n(op.y); break; }
  case "nudge": { const {pieces,li}=layerOf(doc,op); pieces[li].x+=n(op.dx??0); pieces[li].y+=n(op.dy??0); break; }
  case "setSprite": { if(!ids.has(op.sprite)) throw new OpError(`sprite ${op.sprite} not in catalog`); layerOf(doc,op).pieces[layerOf(doc,op).li].sprite=op.sprite; break; }
  case "addPiece": { if(!ids.has(op.sprite)) throw new OpError(`sprite ${op.sprite} not in catalog`); const f=frameAt(doc,op.frame), d=f.dirs[dirIndex(doc,op.dir)]; d.splice(op.layer??d.length,0,{sprite:op.sprite,x:n(op.x),y:n(op.y)}); break; }
  case "removePiece": { const {pieces,li}=layerOf(doc,op); pieces.splice(li,1); break; }
  case "reorder": { const {pieces,li}=layerOf(doc,op), [p]=pieces.splice(li,1); pieces.splice(Math.min(n(op.to),pieces.length),0,p); break; }
  case "setDuration": frameAt(doc,op.frame).duration=msToDuration(op.ms); break;
  case "insertFrame": { const at=op.frame??doc.frames.length, f=op.copyFrom!=null?structuredClone(frameAt(doc,op.copyFrom)):{duration:TICK_MS,sounds:[],dirs:Array.from({length:doc.singleDir?1:4},()=>[])}; doc.frames.splice(at,0,f); break; }
  case "deleteFrame": if(doc.frames.length<=1) throw new OpError("cannot delete the last frame"); frameAt(doc,op.frame); doc.frames.splice(op.frame,1); break;
  case "addSound": frameAt(doc,op.frame).sounds.push({file:String(op.file),x:op.x??0,y:op.y??0}); break;
  case "removeSound": frameAt(doc,op.frame).sounds.splice(op.index??0,1); break;
  default: throw new OpError(`unknown op ${op.op}`); }
}
export function applyOpsPlain(doc, ops) { const out=clone(doc), ids=doc.spriteIds||new Set(); ops.forEach((op,i)=>{try{one(out,op,ids);}catch(e){const x=new OpError(`op #${i}: ${e.message}`);x.index=i;throw x;}}); return out; }
