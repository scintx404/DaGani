export class RpcPeer {
  constructor(send){this._send=send;this._next=1;this._pending=new Map();this.methods=new Map();}
  register(name,fn){this.methods.set(name,fn);return this;}
  notify(method,params={}){this._send(JSON.stringify({jsonrpc:"2.0",method,params}));}
  call(method,params={},timeoutMs=30000){const id=this._next++;return new Promise((resolve,reject)=>{const t=setTimeout(()=>{this._pending.delete(id);reject(new Error(`${method} timed out`));},timeoutMs);this._pending.set(id,{resolve,reject,t});this._send(JSON.stringify({jsonrpc:"2.0",id,method,params}));});}
  failAll(reason="connection closed"){for(const {reject,t} of this._pending.values()){clearTimeout(t);reject(new Error(reason));}this._pending.clear();}
  async handle(raw){let m;try{m=typeof raw==="string"?JSON.parse(raw):raw;}catch{return;}if(m.method===undefined){const p=this._pending.get(m.id);if(!p)return;this._pending.delete(m.id);clearTimeout(p.t);if(m.error)p.reject(Object.assign(new Error(m.error.message),{code:m.error.code,data:m.error.data}));else p.resolve(m.result);return;}const fn=this.methods.get(m.method),reply=b=>{if(m.id!=null)this._send(JSON.stringify({jsonrpc:"2.0",id:m.id,...b}));};if(!fn)return reply({error:{code:-32601,message:`method not found: ${m.method}`}});try{reply({result:await fn(m.params||{})});}catch(e){reply({error:{code:Number.isInteger(e.code)?e.code:-32603,message:String(e.message||e)}});}}
}
