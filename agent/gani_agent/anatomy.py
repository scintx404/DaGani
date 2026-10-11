"""Deterministic Graal anatomy metadata used to constrain planning."""
from __future__ import annotations
import re
DIRS=("up","left","down","right")
ROLE_RULES=(("shadow",r"shadow|feet|ground|circle"),("weapon",r"sword|shield|bow|arrow|weapon|staff|wand|shovel"),("head",r"head|hair|face"),("body",r"body|torso|chest|arm|leg|hand|foot"),("effect",r"spark|flame|smoke|light|magic|fx"))
def classify(source="",label="",comment=""):
 text=f"{source} {label} {comment}".lower();role=next((r for r,rx in ROLE_RULES if re.search(rx,text)),"other")
 return {"role":role,"anchor":"feet" if role=="shadow" else "neck" if role=="head" else "hand" if role=="weapon" else "origin","anchor_offset":{"x":0,"y":0 if role=="shadow" else -16 if role=="head" else 0},"directions":list(DIRS),"layer_priors":{"up":{"shadow":0,"weapon":1,"body":2,"head":3},"left":{"shadow":0,"body":1,"weapon":2,"head":3},"down":{"shadow":0,"body":1,"head":2,"weapon":3},"right":{"shadow":0,"body":1,"weapon":2,"head":3}}}
def enrich(item):
 out=dict(item);out.update(classify(item.get("source",""),item.get("label",""),item.get("comment","")));return out
