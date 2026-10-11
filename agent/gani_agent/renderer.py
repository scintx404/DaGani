"""Contact-sheet renderer for headless fallback and tests."""
from __future__ import annotations
import base64,cv2,numpy as np
from . import gani as G
SCALE=4;CELL_PAD=8
class HeadlessRenderer:
 def __init__(self,sheet_path: str|None=None,sheet_name: str|None=None):self.image=cv2.imread(sheet_path,cv2.IMREAD_UNCHANGED) if sheet_path else None;self.sheet_name=sheet_name
 def _sprite(self,s):
  if self.image is None or s is None:return None
  img=self.image[s.top:s.top+s.height,s.left:s.left+s.width];return img if img.size else None
 def raw(self,doc):
  if self.image is None:return None
  smap=doc.sprite_map();cells=[]
  for fi,f in enumerate(doc.frames):
   for d,pieces in enumerate(f.dirs):
    canvas=np.zeros((192,192),np.uint8);missing=[]
    for p in pieces:
     s=smap.get(p.sprite_id);img=self._sprite(s) if s else None
     if img is None:missing.append(p.sprite);continue
     if img.shape[2]<4:continue
     a=img[:,:,3];y0,x0=int(p.y)+96,int(p.x)+96;h,w=a.shape;sub=canvas[y0:y0+h,x0:x0+w];sub[:]=np.maximum(sub,a[:sub.shape[0],:sub.shape[1]])
    ys,xs=np.nonzero(canvas);cells.append({"frame":fi,"dir":"all" if doc.single_dir else G.DIRS[d],"opaque_px":int(len(xs)),"centroid":[float(xs.mean())-96,float(ys.mean())-96] if len(xs) else None,"missing_images":missing})
  return {"cells":cells}
 def sheet(self,doc,catalog):
  rows=1 if doc.single_dir else 4;cols=max(1,len(doc.frames));cw,ch=96*SCALE//2+CELL_PAD*2,96*SCALE//2+CELL_PAD*2+12;canvas=np.full((rows*ch,cols*cw,3),40,np.uint8);smap=doc.sprite_map()
  for fi,f in enumerate(doc.frames):
   for r in range(rows):
    x0,y0=fi*cw,r*ch;cell=np.full((ch-12,cw,3),90,np.uint8);cx,cy=cw//2,(ch-12)//2;cv2.line(cell,(cx,0),(cx,cell.shape[0]),(0,0,255),1);cv2.line(cell,(0,cy),(cw,cy),(0,0,255),1)
    for p in f.dirs[r]:
     s=smap.get(p.sprite_id);img=self._sprite(s)
     if img is None:continue
     h,w=img.shape[:2];tile=cv2.resize(img,(max(1,w*SCALE//2),max(1,h*SCALE//2)),interpolation=cv2.INTER_NEAREST);ah,aw=tile.shape[:2];ox,oy=cx+int(p.x)//2,cy+int(p.y)//2
     for yy in range(ah):
      for xx in range(aw):
       py,px=oy+yy,ox+xx
       if 0<=py<cell.shape[0] and 0<=px<cell.shape[1] and tile.shape[2]>3 and tile[yy,xx,3]>0:cell[py,px]=tile[yy,xx,:3]
    cv2.putText(cell,f"f{fi} {f.duration_ms}ms",(3,10),cv2.FONT_HERSHEY_SIMPLEX,.3,(255,255,255),1);canvas[y0:y0+ch-12,x0:x0+cw]=cell
  ok,buf=cv2.imencode(".png",canvas);return base64.b64encode(buf.tobytes()).decode()
