"""Sprite pre-processor: exact alpha-tight rects plus Graal anatomy metadata."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import numpy as np
from .anatomy import enrich
try: import cv2
except ImportError: cv2=None
def _load_rgba(path):
 if cv2 is None:raise RuntimeError("opencv-python-headless is required for sprite extraction")
 img=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
 if img is None:raise FileNotFoundError(path)
 if img.ndim==2:img=cv2.cvtColor(img,cv2.COLOR_GRAY2BGRA)
 elif img.shape[2]==3:img=cv2.cvtColor(img,cv2.COLOR_BGR2BGRA)
 return img
def opaque_mask(img,colorkey=None):
 alpha=img[:,:,3]>0
 if colorkey is None and alpha.all():colorkey=tuple(int(c) for c in img[0,0,:3][::-1])
 if colorkey is not None:alpha &= ~(img[:,:,:3]==np.array(colorkey[::-1],dtype=np.uint8)).all(axis=2)
 return alpha.astype(np.uint8)
def extract(path,cell=None,min_area=4,merge_gap=1,colorkey=None,start_index=1000,source=None):
 img=_load_rgba(path);mask=opaque_mask(img,colorkey);h,w=mask.shape;sprites=[]
 if cell:
  cw,ch=cell
  for ty in range(0,h,ch):
   for tx in range(0,w,cw):
    ys,xs=np.nonzero(mask[ty:ty+ch,tx:tx+cw])
    if len(xs)<min_area:continue
    l,t=tx+int(xs.min()),ty+int(ys.min());r,b=tx+int(xs.max())+1,ty+int(ys.max())+1;sprites.append({"rect":[l,t,r-l,b-t],"cell":[tx//cw,ty//ch],"grid_rect":[tx,ty,cw,ch]})
 else:
  k=np.ones((2*merge_gap+1,2*merge_gap+1),np.uint8) if merge_gap>0 else None;m=cv2.dilate(mask,k) if k is not None else mask;n,labels,stats,_=cv2.connectedComponentsWithStats(m,8)
  for i in range(1,n):
   x,y,bw,bh,area=(int(v) for v in stats[i]);sub=mask[y:y+bh,x:x+bw] & (labels[y:y+bh,x:x+bw]==i);ys,xs=np.nonzero(sub)
   if len(xs)>=min_area:sprites.append({"rect":[x+int(xs.min()),y+int(ys.min()),int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1)],"cell":None})
  sprites.sort(key=lambda s:(s["rect"][1]//8,s["rect"][0]))
 src=source or Path(path).name
 for n_,s in enumerate(sprites):
  l,t,sw,sh=s["rect"];s.update({"id":start_index+n_,"source":src,"anchor_bottom_center":[l+sw//2,t+sh],"label":f"{Path(path).stem} #{n_}"});s.update(enrich(s))
 return {"sheet":str(path),"hash":hashlib.sha1(Path(path).read_bytes()).hexdigest(),"size":[w,h],"sprites":sprites}
def extract_cached(path,cache_dir,**kw):
 cache_dir=Path(cache_dir);cache_dir.mkdir(parents=True,exist_ok=True);digest=hashlib.sha1(Path(path).read_bytes()+json.dumps(kw,sort_keys=True,default=str).encode()).hexdigest();f=cache_dir/f"{digest}.json"
 if f.exists():return json.loads(f.read_text())
 out=extract(path,**kw);f.write_text(json.dumps(out));return out
def to_sprite_lines(catalog):return ["SPRITE %4d %15s %4d %4d %4d %4d %s"%(s["id"],s["source"],*s["rect"],s["label"]) for s in catalog["sprites"]]
