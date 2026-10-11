import { EditorAdapter } from "./EditorAdapter.js";
const AGENT_URL = "ws://127.0.0.1:8765";
export function initAiBridge(deps, {enabled=true,url=AGENT_URL,token=null,readToken=null}={}) {
  if (!enabled) return null; const adapter=new EditorAdapter(deps); let ws=null,nextId=1,retry=null,closed=false,authToken=token; const pending=new Map(),listeners=new Set();
  const emit=m=>listeners.forEach(fn=>fn(m));
  function request(method,params={}) { return new Promise((resolve,reject)=>{ const id=nextId++; pending.set(id,{resolve,reject}); if(!ws || ws.readyState!==WebSocket.OPEN){pending.delete(id);reject(new Error("AI sidecar is not connected"));return;} ws.send(JSON.stringify({jsonrpc:"2.0",id,method,params})); }); }
  function notify(method,params={}) { if(ws?.readyState===WebSocket.OPEN) ws.send(JSON.stringify({jsonrpc:"2.0",method,params})); }
  async function connect() { if(closed || ws?.readyState===WebSocket.OPEN || ws?.readyState===WebSocket.CONNECTING)return; if(!authToken && typeof readToken==="function")authToken=await readToken(); if(!authToken)throw new Error("AI sidecar token is missing"); ws=new WebSocket(url); ws.onopen=()=>ws.send(JSON.stringify({auth:authToken})); ws.onmessage=e=>{let m;try{m=JSON.parse(e.data)}catch{return} if(m.id!==undefined&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);if(m.error)p.reject(Object.assign(new Error(m.error.message||"RPC error"),{code:m.error.code,data:m.error.data}));else p.resolve(m.result)}else{emit(m);if(m.method==="state.changed"&&m.params?.by==="user")adapter._onStateChange(m.params)}}; ws.onerror=()=>emit({method:"bridge.error"}); ws.onclose=()=>{pending.forEach(p=>p.reject(new Error("AI sidecar disconnected")));pending.clear();ws=null;if(!closed)retry=setTimeout(()=>connect().catch(()=>{}),2000)}; }
  function disconnect(){closed=true;if(retry)clearTimeout(retry);pending.forEach(p=>p.reject(new Error("AI bridge closed")));pending.clear();ws?.close();ws=null;}
  return {adapter,connect,disconnect,request,notify,onMessage(fn){listeners.add(fn);return()=>listeners.delete(fn)},setToken(v){authToken=v},isConnected(){return ws?.readyState===WebSocket.OPEN}};
}
