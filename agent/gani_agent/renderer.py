"""Contact-sheet renderer used when the editor bridge isn't attached (headless / tests / CLI).

The production path renders through the editor's own export renderer (OffscreenCanvas) via
the bridge. This one draws the same layout from the sprite sheet with OpenCV so the pipeline
can run end to end without a browser. Output: base64 PNG, 4x nearest, labelled grid.
"""
from __future__ import annotations

import base64

import cv2
import numpy as np

from . import gani as G

SCALE = 4
CELL_PAD = 8


class HeadlessRenderer:
    def __init__(self, sheet_path: str, sheet_name: str | None = None):
        self.image = cv2.imread(sheet_path, cv2.IMREAD_UNCHANGED)
        self.sheet_name = sheet_name

    def _sprite(self, s: G.SpriteDef):
        if self.image is None:
            return None
        img = self.image[s.top:s.top + s.height, s.left:s.left + s.width]
        return img if img.size else None

    def raw(self, doc: G.GaniDoc) -> dict | None:
        """Exact per-cell coverage metrics. Only meaningful when the sheet is loaded."""
        if self.image is None:
            return None
        smap = doc.sprite_map()
        cells = []
        for fi, f in enumerate(doc.frames):
            for d, pieces in enumerate(f.dirs):
                canvas = np.zeros((96 * 2, 96 * 2), np.uint8)
                missing = []
                for p in pieces:
                    s = smap.get(p.sprite_id)
                    if not s:
                        missing.append(p.sprite)
                        continue
                    img = self._sprite(s)
                    if img is None or img.shape[2] < 4:
                        continue
                    a = img[:, :, 3]
                    y0, x0 = int(p.y) + 96, int(p.x) + 96
                    h, w = a.shape
                    sub = canvas[y0:y0 + h, x0:x0 + w]
                    sub[:] = np.maximum(sub, a[:sub.shape[0], :sub.shape[1]])
                ys, xs = np.nonzero(canvas)
                cen = [float(xs.mean()) - 96, float(ys.mean()) - 96] if len(xs) else None
                cells.append({"frame": fi, "dir": "all" if doc.single_dir else G.DIRS[d],
                              "opaque_px": int(len(xs)), "centroid": cen, "missing_images": missing})
        return {"cells": cells}

    def sheet(self, doc: G.GaniDoc, catalog: list[dict]) -> str:
        """Contact sheet: rows = directions, columns = frames, labelled. Returns base64 PNG."""
        rows = 1 if doc.single_dir else 4
        cols = max(1, len(doc.frames))
        cw, ch = 96 * SCALE // 2 + CELL_PAD * 2, 96 * SCALE // 2 + CELL_PAD * 2 + 12
        canvas = np.full((rows * ch, cols * cw, 3), 40, np.uint8)
        smap = doc.sprite_map()
        for fi, f in enumerate(doc.frames):
            for r in range(rows):
                x0, y0 = fi * cw, r * ch
                cell = np.full((ch - 12, cw, 3), 90, np.uint8)
                cx, cy = cw // 2, (ch - 12) // 2
                cv2.line(cell, (cx, 0), (cx, cell.shape[0]), (0, 0, 255), 1)
                cv2.line(cell, (0, cy), (cw, cy), (0, 0, 255), 1)
                for p in f.dirs[r]:
                    s = smap.get(p.sprite_id)
                    img = self._sprite(s) if s else None
                    if img is None:
                        continue
                    if img.shape[2] == 4:
                        h, w = img.shape[:2]
                        ox, oy = cx + int(p.x) // 2, cy + int(p.y) // 2
                        tile = cv2.resize(img, (w * SCALE // 2, h * SCALE // 2), interpolation=cv2.INTER_NEAREST)
                        ah, aw = tile.shape[:2]
                        for yy in range(ah):
                            for xx in range(aw):
                                py, px = oy + yy, ox + xx
                                if 0 <= py < cell.shape[0] and 0 <= px < cw and tile[yy, xx, 3] > 0:
                                    cell[py, px] = tile[yy, xx, :3]
                label = f"f{fi} {f.duration_ms}ms"
                cv2.putText(cell, label, (3, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1)
                canvas[y0:y0 + ch - 12, x0:x0 + cw] = cell
        ok, buf = cv2.imencode(".png", canvas)
        return base64.b64encode(buf.tobytes()).decode()
