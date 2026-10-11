const IDENT=/^[A-Za-z_$][\\w$]*$/;
export function lex(name){if(!IDENT.test(name))throw new Error(`bad identifier ${name}`);if(name in globalThis)return globalThis[name];try{return Function(`return typeof ${name} !== "undefined" ? ${name} : undefined`)();}catch{return undefined;}}
export function fn(name){const f=lex(name);return typeof f==="function"?f:null;}
export const SPRITE_INDEX_STRING=-21374783;
export function activeAnimation(){const tm=globalThis.tabManager||lex("tabManager"),tab=tm?.getActiveTab?.();if(tab?.type==="gani"&&tab.data?.ani)return{ani:tab.data.ani,tab,tm};const ani=lex("currentAnimation");return ani?{ani,tab:null,tm}:null;}
export function editorReady(){return typeof globalThis.parseGani==="function"&&!!activeAnimation();}
