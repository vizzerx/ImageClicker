# -*- coding: utf-8 -*-
"""
Image Clicker v3 - เฝ้าหน้าจอแล้วคลิกรูปที่ตรงกับตัวอย่างอัตโนมัติ
------------------------------------------------------------------
ใหม่ในเวอร์ชันนี้:
  • โหมด "ตามลำดับ" รองรับ "กลุ่มยืดหยุ่น" : ขั้นที่ตั้งเป็นยืดหยุ่นและติดกัน
    จะถูกจับเป็นกลุ่มเดียว เจออันไหนก่อนคลิกอันนั้น (เจอพร้อมกันเลือกตามลำดับบนสุด)
  • UI สไตล์ Apple (การ์ดขาว ปุ่มโค้งสีฟ้า segmented control)
  • บันทึก/เปิดพรีเซ็ตได้ (ฝังรูปในไฟล์เดียว) + พรีเซ็ตเริ่มต้นอัตโนมัติ

หยุดฉุกเฉิน: เลื่อนเมาส์ชนมุมซ้ายบนสุดของจอ หรือกด F8
"""

import os
import re
import csv
import time
import json
import base64
import random
import threading
from datetime import datetime, timedelta
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, simpledialog

import numpy as np
import cv2

import sys
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0
except Exception as e:  # pragma: no cover
    pyautogui = None
    _IMPORT_ERR = e

try:
    import keyboard
    HAS_KEYBOARD = True
except Exception:
    HAS_KEYBOARD = False

try:
    import pytesseract
    HAS_OCR = True
    if sys.platform == "win32":
        _default_tesseract = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(_default_tesseract):
            pytesseract.pytesseract.tesseract_cmd = _default_tesseract
except Exception:
    pytesseract = None
    HAS_OCR = False

try:
    import requests
    HAS_REQUESTS = True
except Exception:
    requests = None
    HAS_REQUESTS = False

# exe ที่ compile ด้วย PyInstaller (--onefile) จะรัน __file__ จากโฟลเดอร์ชั่วคราวที่แตกไฟล์
# (sys._MEIPASS) ไม่ใช่โฟลเดอร์จริงของ .exe ต้องเช็ค sys.frozen ก่อน ไม่งั้นหา
# default_preset.json / ไอคอน / โฟลเดอร์ results ที่วางคู่ .exe ไม่เจอ
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PRESET = os.path.join(APP_DIR, "default_preset.json")
RESULTS_DIR = os.path.join(APP_DIR, "results")
# ไฟล์เก็บ token/chat id ของ Telegram แยกจาก default_preset.json โดยเจตนา
# (preset จะแชร์/แจกจ่ายได้ ห้ามมี secret หลุดไปด้วย) ต้องอยู่ใน .gitignore เสมอ
BOT_CONFIG_PATH = os.path.join(APP_DIR, "bot_config.json")

# ---- จานสีสไตล์ Apple ----
BG      = "#f5f5f7"
CARD    = "#ffffff"
TEXT    = "#1d1d1f"
SUBTLE  = "#6e6e73"
BORDER  = "#d2d2d7"
TRACK   = "#e8e8ed"
ACCENT  = "#0071e3"
ACCENT2 = "#0077ed"
DANGER  = "#ff3b30"
DANGER2 = "#ff5147"
GREEN   = "#34c759"


# ----------------------------------------------------------------------
# ตรวจจับรูปภาพ + แปลงรูป
# ----------------------------------------------------------------------
def non_max_suppression(boxes, scores, overlap_thresh=0.3):
    if len(boxes) == 0:
        return []
    boxes = np.array(boxes, dtype=float)
    scores = np.array(scores, dtype=float)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (area[i] + area[order[1:]] - inter)
        order = order[1:][ovr <= overlap_thresh]
    return [boxes[i].astype(int).tolist() for i in keep]


def find_matches(screen_bgr, template_bgr, threshold=0.8, scales=(1.0,)):
    th0, tw0 = template_bgr.shape[:2]
    boxes, scores = [], []
    for s in scales:
        tw, th = max(1, int(tw0 * s)), max(1, int(th0 * s))
        if tw > screen_bgr.shape[1] or th > screen_bgr.shape[0]:
            continue
        tmpl = cv2.resize(template_bgr, (tw, th)) if s != 1.0 else template_bgr
        res = cv2.matchTemplate(screen_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for x, y in zip(xs, ys):
            boxes.append([x, y, x + tw, y + th])
            scores.append(float(res[y, x]))
    keep = non_max_suppression(boxes, scores, 0.3)
    return [((b[0] + b[2]) // 2, (b[1] + b[3]) // 2, b[2] - b[0], b[3] - b[1]) for b in keep]


def grab_screen(region=None):
    """จับภาพหน้าจอเป็น numpy BGR
    ใช้ mss ก่อน (ไม่ต้องพึ่ง Pillow/pyscreeze ทำงานบน Python ใหม่ ๆ ได้)
    ถ้าไม่มี mss ค่อย fallback ไปใช้ pyautogui"""
    try:
        import mss
        with mss.mss() as sct:
            if region:
                l, t, w, h = region
                mon = {"left": int(l), "top": int(t), "width": int(w), "height": int(h)}
            else:
                mon = sct.monitors[1]   # จอหลัก
            raw = sct.grab(mon)
            return cv2.cvtColor(np.array(raw), cv2.COLOR_BGRA2BGR)
    except Exception:
        img = pyautogui.screenshot(region=region)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def ocr_digits(region, tesseract_path=None):
    """OCR ตัวเลข (+เครื่องหมายจุลภาค) จากพื้นที่หน้าจอที่กำหนด คืน int หรือ None"""
    if not HAS_OCR or not region:
        return None
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    try:
        img = grab_screen(region)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,"
        for flag in (cv2.THRESH_BINARY, cv2.THRESH_BINARY_INV):
            _, th = cv2.threshold(gray, 0, 255, flag + cv2.THRESH_OTSU)
            text = pytesseract.image_to_string(th, config=cfg)
            digits = re.sub(r"[^0-9]", "", text)
            if digits:
                return int(digits)
        return None
    except Exception:
        return None


def img_to_b64(img_bgr):
    ok, buf = cv2.imencode(".png", img_bgr)
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def b64_to_img(b64):
    data = base64.b64decode(b64.encode("ascii"))
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def build_groups(flex_flags):
    """ขั้นยืดหยุ่นที่ติดกัน = 1 กลุ่ม priority ; ขั้นปกติ = strict เดี่ยว"""
    groups, i, n = [], 0, len(flex_flags)
    while i < n:
        if flex_flags[i]:
            j = i
            while j < n and flex_flags[j]:
                j += 1
            groups.append(("priority", list(range(i, j))))
            i = j
        else:
            groups.append(("strict", [i]))
            i += 1
    return groups


# ----------------------------------------------------------------------
# หยุดอัตโนมัติ / ตัวช่วยคำนวณ / รายงาน Telegram — ฟังก์ชันล้วน (pure)
# ไม่พึ่ง self/Tkinter จึงทดสอบได้ตรง ๆ ด้วย pytest (ดู tests/test_pure_helpers.py)
# ----------------------------------------------------------------------
def compute_stop_at_from_duration(now_ts: float, hours: float) -> float:
    """คืน epoch timestamp ที่จะหยุด เมื่อผู้ใช้ระบุ 'ระยะเวลา' เป็นชั่วโมง (ทศนิยมได้)"""
    if hours <= 0:
        raise ValueError("จำนวนชั่วโมงต้องมากกว่า 0")
    return now_ts + hours * 3600.0


def compute_stop_at_from_clock(now_ts: float, hour: int, minute: int) -> float:
    """คืน epoch timestamp ของเวลานาฬิกา HH:MM ที่จะถึงถัดไป
    (วันนี้ถ้ายังไม่ถึง ไม่งั้นเลื่อนไปพรุ่งนี้)"""
    now_dt = datetime.fromtimestamp(now_ts)
    candidate = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_dt:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def parse_hhmm(text: str) -> tuple[int, int]:
    """แปลงข้อความ 'HH:MM' เป็น (hour, minute) โยน ValueError ถ้ารูปแบบผิด"""
    m = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)\s*", text or "")
    if not m:
        raise ValueError("รูปแบบเวลาต้องเป็น HH:MM เช่น 22:30")
    return int(m.group(1)), int(m.group(2))


def format_remaining(seconds_left: float) -> tuple[int, int]:
    """แปลงวินาทีที่เหลือเป็น (ชั่วโมง, นาที) ปัดเศษวินาทีขึ้น ไม่ติดลบ"""
    seconds_left = max(0, int(seconds_left + 0.999))
    h, rem = divmod(seconds_left, 3600)
    return h, rem // 60


def compute_avg_round_seconds(results: list) -> float | None:
    """เฉลี่ย elapsed (วินาที) ของทุกรอบที่บันทึกไว้ คืน None ถ้ายังไม่มีข้อมูล"""
    elapsed_vals = [r["elapsed"] for r in results if isinstance(r.get("elapsed"), (int, float))]
    if not elapsed_vals:
        return None
    return sum(elapsed_vals) / len(elapsed_vals)


def compute_hearts_estimate(avg_seconds: float, hearts: int) -> float:
    """เวลารวมที่คาดว่าจะใช้ (วินาที) = ค่าเฉลี่ยต่อรอบ x จำนวนหัวใจ"""
    if avg_seconds < 0 or hearts < 0:
        raise ValueError("ค่าต้องไม่ติดลบ")
    return avg_seconds * hearts


def sum_results(results: list) -> tuple[int, int]:
    """รวม Coins/XP จากรายการผลลัพธ์ (ข้าม field ที่ไม่ใช่ int เช่น OCR อ่านไม่ออก = '')"""
    coins_sum = sum(r["coins"] for r in results if isinstance(r["coins"], int))
    xp_sum = sum(r["xp"] for r in results if isinstance(r["xp"], int))
    return coins_sum, xp_sum


def format_telegram_report(coins_sum: int, xp_sum: int, round_num: int, prefix: str = "") -> str:
    """สร้างข้อความรายงานภาษาไทยสำหรับส่งเข้า Telegram
    prefix = คำนำหน้าที่ผู้ใช้ตั้งเอง (เช่น ชื่อเครื่อง) แยกบรรทัดแรก ใส่เมื่อไม่ว่างเท่านั้น"""
    header = f"{prefix}\n" if prefix else ""
    return (f"{header}รายงานผลการเล่น\n"
            f"รอบที่เล่นแล้ว: {round_num}\n"
            f"รวม Coins: {coins_sum:,}\n"
            f"รวม XP: {xp_sum:,}")


def build_telegram_url(token: str) -> str:
    return f"https://api.telegram.org/bot{token}/sendMessage"


# ----------------------------------------------------------------------
# วิดเจ็ตสไตล์ Apple
# ----------------------------------------------------------------------
def _round_pts(x1, y1, x2, y2, r):
    return [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
            x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]


class PillButton(tk.Canvas):
    """ปุ่มมุมโค้งสไตล์ Apple"""
    def __init__(self, parent, text, command, kind="primary",
                 width=150, height=42, font=("Segoe UI", 11, "bold"), bg=CARD):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.command = command
        self._cw, self._ch, self._r = width, height, 11
        self.font = font
        self._text = text
        self._set_kind(kind)
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", self._on_configure)
        self._draw(False)

    def _on_configure(self, e):
        if e.width > 1 and e.height > 1 and (e.width != self._cw or e.height != self._ch):
            self._cw, self._ch = e.width, e.height
            self._draw(False)

    def _set_kind(self, kind):
        self.kind = kind
        self._fill, self._fillh, self._fg = {
            "primary":   (ACCENT, ACCENT2, "#ffffff"),
            "danger":    (DANGER, DANGER2, "#ffffff"),
            "secondary": (TRACK, "#dcdce1", TEXT),
        }[kind]

    def set_state(self, text=None, kind=None):
        if kind:
            self._set_kind(kind)
        if text is not None:
            self._text = text
        self._draw(False)

    def _on_click(self, _e):
        if self.command:
            self.command()

    def _draw(self, hover):
        self.delete("all")
        fill = self._fillh if hover else self._fill
        self.create_polygon(_round_pts(1, 1, self._cw-1, self._ch-1, self._r),
                            smooth=True, fill=fill, outline=fill)
        self.create_text(self._cw//2, self._ch//2, text=getattr(self, "_text", ""),
                         fill=self._fg, font=self.font)

    def config_text(self, text):
        self._text = text
        self._draw(False)


class IconButton(tk.Canvas):
    """ปุ่มกลมเล็ก เช่น ▲ ▼ +"""
    def __init__(self, parent, glyph, command, size=34, bg=CARD,
                 fg=TEXT, fill=TRACK, font=("Segoe UI", 12)):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        self.command, self.s, self.glyph = command, size, glyph
        self.fg, self.fill = fg, fill
        self.font = font
        self.bind("<Enter>", lambda e: self._draw("#dcdce1"))
        self.bind("<Leave>", lambda e: self._draw(self.fill))
        self.bind("<Button-1>", lambda e: command() if command else None)
        self._draw(self.fill)

    def _draw(self, fill):
        self.delete("all")
        self.create_polygon(_round_pts(1, 1, self.s-1, self.s-1, 9),
                            smooth=True, fill=fill, outline=fill)
        self.create_text(self.s//2, self.s//2, text=self.glyph,
                         fill=self.fg, font=self.font)


class Segmented(tk.Canvas):
    """segmented control 2 ตัวเลือกสไตล์ Apple"""
    def __init__(self, parent, options, values, variable, command=None,
                 width=440, height=36, bg=CARD, font=("Segoe UI", 10, "bold")):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.options, self.values, self.var = options, values, variable
        self.command, self._cw, self._ch, self.font = command, width, height, font
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", self._on_configure)
        self.redraw()

    def _on_configure(self, e):
        if e.width > 1 and e.height > 1 and (e.width != self._cw or e.height != self._ch):
            self._cw, self._ch = e.width, e.height
            self.redraw()

    def _click(self, e):
        idx = 0 if e.x < self._cw/2 else 1
        self.var.set(self.values[idx])
        self.redraw()
        if self.command:
            self.command()

    def redraw(self):
        self.delete("all")
        self.create_polygon(_round_pts(0, 0, self._cw, self._ch, self._ch//2),
                            smooth=True, fill=TRACK, outline=TRACK)
        sel = 0 if self.var.get() == self.values[0] else 1
        half = self._cw/2
        pad = 3
        x1 = pad + sel*half
        x2 = x1 + half - 2*pad
        self.create_polygon(_round_pts(x1, pad, x2, self._ch-pad, (self._ch-2*pad)//2),
                            smooth=True, fill=CARD, outline=CARD)
        for i, label in enumerate(self.options):
            cx = half/2 + i*half
            self.create_text(cx, self._ch/2, text=label,
                             fill=(TEXT if i == sel else SUBTLE), font=self.font)


def make_card(parent, title=None, font=None, fill="x", expand=False):
    """กล่องการ์ดขาวมุมโค้ง (จำลองด้วยขอบบาง ๆ)"""
    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill=fill, padx=8, pady=6, expand=expand)
    card = tk.Frame(outer, bg=CARD, highlightbackground=BORDER,
                    highlightthickness=1, bd=0)
    card.pack(fill="both", expand=True)
    if title:
        tk.Label(card, text=title, bg=CARD, fg=SUBTLE,
                 font=(font, 10, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
    return card


# ----------------------------------------------------------------------
# ลากเลือกพื้นที่บนจอ
# ----------------------------------------------------------------------
class RegionSelector:
    def __init__(self, root):
        self.root, self.result = root, None

    def select(self):
        top = tk.Toplevel(self.root)
        top.attributes("-fullscreen", True)
        try:
            top.attributes("-alpha", 0.25)
        except Exception:
            pass
        top.configure(bg="black")
        top.attributes("-topmost", True)
        top.config(cursor="cross")
        cv = tk.Canvas(top, bg="black", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_text(top.winfo_screenwidth()//2, 30,
                       text="ลากเมาส์ครอบพื้นที่ที่ต้องการ  (กด Esc เพื่อยกเลิก)",
                       fill="white", font=("Segoe UI", 16))
        st = {"x0": 0, "y0": 0, "rect": None}

        def down(e):
            st["x0"], st["y0"] = e.x, e.y
            st["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#0071e3", width=2)

        def move(e):
            if st["rect"]:
                cv.coords(st["rect"], st["x0"], st["y0"], e.x, e.y)

        def up(e):
            if st["rect"] is None:
                return
            l, t = min(st["x0"], e.x), min(st["y0"], e.y)
            w, h = abs(e.x-st["x0"]), abs(e.y-st["y0"])
            if w > 3 and h > 3:
                self.result = (l, t, w, h)
            top.destroy()

        cv.bind("<ButtonPress-1>", down)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", up)
        top.bind("<Escape>", lambda e: top.destroy())
        top.grab_set()
        self.root.wait_window(top)
        return self.result


class ScrollableFrame(tk.Frame):
    """คอลัมน์ที่เลื่อน (scroll) แนวตั้งได้ — ใช้เมื่อการ์ดข้างในรวมกันสูงเกินหน้าต่าง"""
    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _on_inner_configure(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self.canvas.itemconfig(self._win, width=e.width)

    def _bind_wheel(self, _e=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def _unbind_wheel(self, _e=None):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, e):
        # Windows: delta เป็นทวีคูณของ 120 / macOS: delta เป็นเลขน้อย ๆ
        step = int(-e.delta / 120) if abs(e.delta) >= 120 else int(-e.delta)
        self.canvas.yview_scroll(step, "units")


# ----------------------------------------------------------------------
# โปรแกรมหลัก
# ----------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Image Clicker")
        root.configure(bg=BG)
        root.geometry("980x980")
        root.minsize(700, 600)

        icon_ico = os.path.join(APP_DIR, "app_icon.ico")
        icon_png = os.path.join(APP_DIR, "app_icon.png")
        icon_set = False
        if sys.platform == "win32" and os.path.exists(icon_ico):
            # .ico ผ่าน Win32 GDI ตรง ๆ เชื่อถือได้กว่า iconphoto (ไม่ต้องพึ่งว่า Tk เวอร์ชันนั้นรองรับ PNG ไหม)
            # default=... ทำให้ Toplevel ที่เปิดต่อ (เช่นตอนลากเลือกพื้นที่) ได้ไอคอนเดียวกันด้วย
            try:
                root.iconbitmap(default=icon_ico)
                icon_set = True
            except Exception:
                pass
        if not icon_set and os.path.exists(icon_png):
            try:
                self._icon_img = tk.PhotoImage(file=icon_png)   # เก็บ reference กันโดนเก็บขยะ
                root.iconphoto(True, self._icon_img)
            except Exception:
                pass

        # ฟอนต์สะอาดที่สุดที่มีในเครื่อง
        fams = set(tkfont.families(root))
        self.ff = next((f for f in ["SF Pro Text", "Helvetica Neue",
                                    "Segoe UI", "Arial"] if f in fams), "TkDefaultFont")

        self.steps = []     # [{"name","clicks","flexible","img"}]
        self.region = None
        self.running = False
        self.worker = None
        self.recent_clicks = []
        self.cfg = {}

        self.coins_region = None
        self.xp_region = None
        self.tesseract_path = ""
        self.results = []
        self.round_num = 0
        self.round_start_time = None
        self.results_csv_path = None

        self.stop_at = None            # epoch timestamp ที่จะหยุดอัตโนมัติ (None = ปิด)
        self.auto_stop_job = None      # after() id ของ tick นับถอยหลัง

        self._telegram_thread = None
        self._telegram_stop_flag = None

        self._setup_style()
        self._build_ui()
        self.load_bot_config()

        if pyautogui is None:
            messagebox.showerror("ใช้งานไม่ได้",
                "ติดตั้ง pyautogui ไม่สำเร็จ:\n%s" % _IMPORT_ERR)

        if HAS_KEYBOARD:
            try:
                keyboard.add_hotkey("f8", self.toggle)
            except Exception:
                pass

        if os.path.exists(DEFAULT_PRESET):
            self.load_preset(DEFAULT_PRESET, silent=True)
            self.log("โหลดพรีเซ็ตเริ่มต้นอัตโนมัติแล้ว")

    def _setup_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("A.Treeview", background=CARD, fieldbackground=CARD,
                     foreground=TEXT, rowheight=32, borderwidth=0,
                     font=(self.ff, 10))
        st.configure("A.Treeview.Heading", background=CARD, foreground=SUBTLE,
                     font=(self.ff, 9, "bold"), borderwidth=0, relief="flat")
        st.map("A.Treeview", background=[("selected", ACCENT)],
               foreground=[("selected", "#ffffff")])
        st.configure("A.Horizontal.TScale", background=CARD, troughcolor=TRACK)
        st.configure("A.TSpinbox", fieldbackground="#ffffff", background=CARD,
                     bordercolor=BORDER, arrowsize=12)

    # ---------------- UI ----------------
    def _lbl(self, parent, text, fg=TEXT, **kw):
        return tk.Label(parent, text=text, bg=CARD, fg=fg, font=(self.ff, 10), **kw)

    def _build_ui(self):
        # ----- ปุ่มเริ่ม (เต็มความกว้าง ด้านล่างสุด) -----
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(side="bottom", fill="x", padx=18, pady=(2, 8))
        tk.Label(footer, text="หยุดฉุกเฉิน: เลื่อนเมาส์ชนมุมซ้ายบนสุดของจอ หรือกด F8",
                 bg=BG, fg=DANGER, font=(self.ff, 9)).pack(pady=(2, 4))
        self.btn_start = PillButton(footer, "เริ่มทำงาน  (F8)", self.toggle,
                                    "primary", width=900, height=48,
                                    font=(self.ff, 13, "bold"), bg=BG)
        self.btn_start.pack(fill="x")

        # ----- พื้นที่ 2 คอลัมน์ (ซ้ายกว้างกว่าขวา) -----
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)

        self.left_scroll = ScrollableFrame(main, bg=BG)
        self.left_scroll.grid(row=0, column=0, sticky="nsew")
        left = self.left_scroll.inner
        right = tk.Frame(main, bg=BG); right.grid(row=0, column=1, sticky="nsew")

        # ===== คอลัมน์ซ้าย =====
        # ----- ขั้นตอน -----
        c1 = make_card(left, "ขั้นตอน  (เลือกขั้นแล้วจัดลำดับ / ตั้งยืดหยุ่นได้)", self.ff,
                       fill="x")
        body = tk.Frame(c1, bg=CARD); body.pack(fill="both", expand=True, padx=16, pady=10)
        tv = ttk.Treeview(body, style="A.Treeview", height=5,
                          columns=("clicks", "mode", "opts"), show="tree headings", selectmode="browse")
        tv.heading("#0", text="ขั้นตอน"); tv.heading("clicks", text="คลิก")
        tv.heading("mode", text="ชนิด"); tv.heading("opts", text="ตัวเลือกเพิ่ม")
        tv.column("#0", width=180, anchor="w")
        tv.column("clicks", width=42, anchor="center")
        tv.column("mode", width=80, anchor="center")
        tv.column("opts", width=150, anchor="w")
        tv.pack(side="left", fill="both", expand=True)
        tv.bind("<<TreeviewSelect>>", self._on_step_select)
        self.tree = tv
        order = tk.Frame(body, bg=CARD); order.pack(side="left", fill="y", padx=(8, 0))
        IconButton(order, "▲", self.move_up).pack(pady=3)
        IconButton(order, "▼", self.move_down).pack(pady=3)

        act1 = tk.Frame(c1, bg=CARD); act1.pack(fill="x", padx=16, pady=(0, 4))
        PillButton(act1, "จับภาพจากจอ", self.capture_template, "primary",
                   width=150, height=36, font=(self.ff, 10, "bold")).pack(side="left")
        PillButton(act1, "เพิ่มจากไฟล์", self.add_image, "secondary",
                   width=130, height=36, font=(self.ff, 10, "bold")).pack(side="left", padx=6)
        PillButton(act1, "จับตำแหน่งตายตัว", self.capture_position, "secondary",
                   width=150, height=36, font=(self.ff, 10, "bold")).pack(side="left", padx=6)
        tk.Label(c1, text="ขั้น 'ตำแหน่งตายตัว' จะคลิกที่พิกัดเดิมเสมอ ไม่ต้องจับคู่รูป\n"
                 "เหมาะกับปุ่มที่ตำแหน่งคงที่แต่เนื้อหาเปลี่ยน เช่น ปุ่มตัวเลข",
                 bg=CARD, fg=SUBTLE, font=(self.ff, 9), justify="left").pack(anchor="w", padx=16, pady=(0, 4))
        act2 = tk.Frame(c1, bg=CARD); act2.pack(fill="x", padx=16, pady=(0, 6))
        PillButton(act2, "สลับ ลำดับ/ยืดหยุ่น", self.toggle_flex, "secondary",
                   width=170, height=36, font=(self.ff, 10, "bold")).pack(side="left")
        PillButton(act2, "ลบขั้นที่เลือก", self.remove_image, "secondary",
                   width=120, height=36, font=(self.ff, 10, "bold")).pack(side="left", padx=6)

        rc = tk.Frame(c1, bg=CARD); rc.pack(fill="x", padx=16, pady=(0, 8))
        self._lbl(rc, "จำนวนคลิก:").pack(side="left")
        self.var_clicks = tk.IntVar(value=1)
        ttk.Spinbox(rc, from_=1, to=20, textvariable=self.var_clicks, width=5,
                    style="A.TSpinbox").pack(side="left", padx=6)
        PillButton(rc, "ใช้กับขั้นที่เลือก", self.apply_clicks, "secondary",
                   width=150, height=32, font=(self.ff, 9, "bold")).pack(side="left")

        # --- คุณสมบัติเฉพาะของขั้น (ลองใช้ค่าเดี่ยว/ตั้งเอง/ทำต่อเมื่อก่อนหน้าสำเร็จ) ---
        prop = tk.Frame(c1, bg=CARD); prop.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(prop, text="คุณสมบัติของขั้นที่เลือก  (ค่าว่าง = ใช้ค่ารวม)",
                 bg=CARD, fg=SUBTLE, font=(self.ff, 9, "bold")).pack(anchor="w", pady=(0, 4))
        self.var_step_retries = tk.StringVar(value="")
        self.var_step_gap = tk.StringVar(value="")
        self.var_step_timeout = tk.StringVar(value="")
        self.var_step_cd = tk.StringVar(value="")
        self.var_step_reqprev = tk.BooleanVar(value=False)
        self.var_step_capture = tk.BooleanVar(value=False)

        def prop_row(label, var, lo, hi, inc, tooltip=""):
            r = tk.Frame(prop, bg=CARD); r.pack(fill="x", pady=1)
            self._lbl(r, label, anchor="w").pack(side="left")
            ttk.Spinbox(r, from_=lo, to=hi, increment=inc, textvariable=var,
                        width=8, style="A.TSpinbox").pack(side="right")
        prop_row("ลองใหม่ (ครั้ง, ว่าง=รวม)", self.var_step_retries, 0, 99, 1)
        prop_row("หน่วงหลังคลิก (วิ, ว่าง=รวม)", self.var_step_gap, 0, 30, 0.5)
        prop_row("รอไม่เกิน (วิ, ว่าง=รวม, 0=ตลอด)", self.var_step_timeout, 0, 120, 1)
        prop_row("ไม่ทำซ้ำหลังสำเร็จ (วิ, ว่าง=รวม, 0=ปิด)", self.var_step_cd, 0, 600, 1)
        tk.Checkbutton(prop, text="ทำต่อเมื่อขั้นก่อนหน้าสำเร็จ (ข้ามถ้าก่อนหน้าล้มเหลว)",
                       variable=self.var_step_reqprev, bg=CARD, fg=TEXT, font=(self.ff, 9),
                       activebackground=CARD, selectcolor=CARD).pack(anchor="w", pady=(4, 6))
        tk.Checkbutton(prop, text="จับผลลัพธ์ (OCR Coins/XP) ตอนเจอขั้นนี้ — ใช้กับ 'บันทึกผลลัพธ์การเล่น'",
                       variable=self.var_step_capture, bg=CARD, fg=TEXT, font=(self.ff, 9),
                       activebackground=CARD, selectcolor=CARD).pack(anchor="w", pady=(0, 6))
        self.btn_apply_props = PillButton(prop, "บันทึกคุณสมบัติลงขั้นที่เลือก", self.apply_step_props,
                                          "secondary", width=230, height=30,
                                          font=(self.ff, 9, "bold"))
        self.btn_apply_props.pack(fill="x")

        # ----- โหมด -----
        c2 = make_card(left, "โหมดการทำงาน", self.ff)
        mbox = tk.Frame(c2, bg=CARD); mbox.pack(fill="x", padx=16, pady=10)
        self.var_mode = tk.StringVar(value="sequence")
        Segmented(mbox, ["ตามลำดับ (มีกลุ่มยืดหยุ่น)", "สแกนทั้งหมด"],
                  ["sequence", "scan_all"], self.var_mode, width=460,
                  font=(self.ff, 10, "bold")).pack(fill="x")
        self.var_loop = tk.BooleanVar(value=True)
        tk.Checkbutton(c2, text="ทำซ้ำวนลูป (ครบทุกขั้นแล้วเริ่มใหม่)", variable=self.var_loop,
                       bg=CARD, fg=TEXT, font=(self.ff, 10), activebackground=CARD,
                       selectcolor=CARD).pack(anchor="w", padx=14, pady=(0, 12))

        # ----- หยุดทำงานอัตโนมัติ -----
        c2c = make_card(left, "หยุดทำงานอัตโนมัติ", self.ff)
        self.var_stop_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(c2c, text="เปิดใช้งานหยุดอัตโนมัติ", variable=self.var_stop_enabled,
                       bg=CARD, fg=TEXT, font=(self.ff, 10, "bold"), activebackground=CARD,
                       selectcolor=CARD).pack(anchor="w", padx=14, pady=(8, 4))

        self.var_stop_mode = tk.StringVar(value="duration")
        smbox = tk.Frame(c2c, bg=CARD); smbox.pack(fill="x", padx=14, pady=(0, 6))
        Segmented(smbox, ["ตามระยะเวลา", "ตามเวลานาฬิกา"], ["duration", "clock"],
                  self.var_stop_mode, width=350, font=(self.ff, 9, "bold")).pack(fill="x")

        self.var_stop_duration = tk.DoubleVar(value=1.0)
        sdr = tk.Frame(c2c, bg=CARD); sdr.pack(fill="x", padx=14, pady=2)
        self._lbl(sdr, "ระยะเวลา (ชั่วโมง)", anchor="w").pack(side="left")
        ttk.Spinbox(sdr, from_=0.1, to=24, increment=0.1, textvariable=self.var_stop_duration,
                    width=8, style="A.TSpinbox").pack(side="right")

        self.var_stop_clock = tk.StringVar(value="")
        scr = tk.Frame(c2c, bg=CARD); scr.pack(fill="x", padx=14, pady=(2, 8))
        self._lbl(scr, "เวลานาฬิกา (HH:MM)", anchor="w").pack(side="left")
        tk.Entry(scr, textvariable=self.var_stop_clock, width=8, justify="center").pack(side="right")

        PillButton(c2c, "คำนวณจากค่าเฉลี่ย...", self.open_stop_calculator, "secondary",
                   width=190, height=32, font=(self.ff, 9, "bold")).pack(anchor="w", padx=14, pady=(0, 8))

        self.lbl_stop_countdown = tk.Label(c2c, text="", bg=CARD, fg=ACCENT,
                                           font=(self.ff, 9, "bold"), justify="left")
        self.lbl_stop_countdown.pack(anchor="w", padx=14, pady=(0, 12))

        # ----- บันทึกผลลัพธ์การเล่น -----
        c2b = make_card(left, "บันทึกผลลัพธ์การเล่น", self.ff)
        self.var_save_results = tk.BooleanVar(value=False)
        tk.Checkbutton(c2b, text="บันทึกผลลัพธ์การเล่น (OCR Coins/XP)", variable=self.var_save_results,
                       command=self._toggle_results_section, bg=CARD, fg=TEXT, font=(self.ff, 10, "bold"),
                       activebackground=CARD, selectcolor=CARD).pack(anchor="w", padx=14, pady=(8, 4))

        self.results_frame = tk.Frame(c2b, bg=CARD)

        if not HAS_OCR:
            tk.Label(self.results_frame, text="ไม่พบไลบรารี pytesseract — ติดตั้งด้วย  pip install pytesseract\n"
                     "และติดตั้งโปรแกรม Tesseract-OCR บนเครื่อง (ดู README)",
                     bg=CARD, fg=DANGER, font=(self.ff, 9), justify="left").pack(anchor="w", padx=14, pady=(0, 6))

        rg = tk.Frame(self.results_frame, bg=CARD); rg.pack(fill="x", padx=14, pady=(0, 2))
        PillButton(rg, "เลือกพื้นที่ Coins", self.pick_coins_region, "secondary",
                   width=140, height=32, font=(self.ff, 9, "bold")).pack(side="left")
        self.lbl_coins_region = self._lbl(rg, "ยังไม่เลือก", fg=SUBTLE); self.lbl_coins_region.pack(side="left", padx=6)

        rg2 = tk.Frame(self.results_frame, bg=CARD); rg2.pack(fill="x", padx=14, pady=(2, 6))
        PillButton(rg2, "เลือกพื้นที่ XP", self.pick_xp_region, "secondary",
                   width=140, height=32, font=(self.ff, 9, "bold")).pack(side="left")
        self.lbl_xp_region = self._lbl(rg2, "ยังไม่เลือก", fg=SUBTLE); self.lbl_xp_region.pack(side="left", padx=6)

        tk.Label(self.results_frame,
                 text="ติ๊ก 'จับผลลัพธ์ (OCR Coins/XP)' ที่ขั้นซึ่งแสดงหน้าผลลัพธ์ ในช่อง\n"
                      "'คุณสมบัติของขั้นที่เลือก' ด้านบน (ใช้ได้เฉพาะโหมด 'ตามลำดับ')",
                 bg=CARD, fg=SUBTLE, font=(self.ff, 9), justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        tvbody = tk.Frame(self.results_frame, bg=CARD); tvbody.pack(fill="both", expand=True, padx=14)
        cols = ("round", "start", "end", "elapsed", "coins", "xp")
        rtv = ttk.Treeview(tvbody, style="A.Treeview", height=6, columns=cols, show="headings")
        heads = {"round": "รอบ", "start": "เริ่ม", "end": "จบ", "elapsed": "ใช้เวลา(วิ)",
                 "coins": "Coins", "xp": "XP"}
        widths = {"round": 40, "start": 70, "end": 70, "elapsed": 70, "coins": 80, "xp": 60}
        for c in cols:
            rtv.heading(c, text=heads[c])
            rtv.column(c, width=widths[c], anchor="center")
        rtv.pack(fill="both", expand=True)
        self.res_tv = rtv

        self.lbl_totals = tk.Label(self.results_frame, text="รวม Coins: 0    รวม XP: 0",
                                   bg=CARD, fg=TEXT, font=(self.ff, 10, "bold"))
        self.lbl_totals.pack(anchor="w", padx=14, pady=(8, 0))

        rbtn = tk.Frame(self.results_frame, bg=CARD); rbtn.pack(fill="x", padx=14, pady=(6, 12))
        PillButton(rbtn, "ส่งออกตาราง", self.export_results, "secondary",
                   width=110, height=32, font=(self.ff, 9, "bold")).pack(side="left")
        PillButton(rbtn, "ล้างตาราง", self.clear_results, "secondary",
                   width=100, height=32, font=(self.ff, 9, "bold")).pack(side="left", padx=6)

        # ----- แจ้งเตือนผ่าน Telegram -----
        c2d = make_card(left, "แจ้งเตือนผ่าน Telegram", self.ff)
        self.var_bot_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(c2d, text="เปิดใช้งานแจ้งเตือน Telegram", variable=self.var_bot_enabled,
                       command=self.save_bot_config, bg=CARD, fg=TEXT, font=(self.ff, 10, "bold"),
                       activebackground=CARD, selectcolor=CARD).pack(anchor="w", padx=14, pady=(8, 4))

        if not HAS_REQUESTS:
            tk.Label(c2d, text="ไม่พบไลบรารี requests — ติดตั้งด้วย  pip install requests",
                     bg=CARD, fg=DANGER, font=(self.ff, 9), justify="left").pack(anchor="w", padx=14, pady=(0, 6))

        self.var_bot_token = tk.StringVar(value="")
        btr = tk.Frame(c2d, bg=CARD); btr.pack(fill="x", padx=14, pady=2)
        self._lbl(btr, "Bot Token", anchor="w").pack(side="left")
        e_token = tk.Entry(btr, textvariable=self.var_bot_token, width=22, show="*")
        e_token.pack(side="right")
        e_token.bind("<FocusOut>", lambda e: self.save_bot_config())

        self.var_bot_chat_id = tk.StringVar(value="")
        bcr = tk.Frame(c2d, bg=CARD); bcr.pack(fill="x", padx=14, pady=2)
        self._lbl(bcr, "Chat ID", anchor="w").pack(side="left")
        e_chat = tk.Entry(bcr, textvariable=self.var_bot_chat_id, width=22)
        e_chat.pack(side="right")
        e_chat.bind("<FocusOut>", lambda e: self.save_bot_config())

        self.var_bot_prefix = tk.StringVar(value="")
        bpr = tk.Frame(c2d, bg=CARD); bpr.pack(fill="x", padx=14, pady=2)
        self._lbl(bpr, "คำนำหน้าข้อความ (เช่น ชื่อเครื่อง)", anchor="w").pack(side="left")
        e_prefix = tk.Entry(bpr, textvariable=self.var_bot_prefix, width=22)
        e_prefix.pack(side="right")
        e_prefix.bind("<FocusOut>", lambda e: self.save_bot_config())

        self.var_bot_interval = tk.IntVar(value=30)
        bir = tk.Frame(c2d, bg=CARD); bir.pack(fill="x", padx=14, pady=(2, 8))
        self._lbl(bir, "รายงานทุกกี่นาที", anchor="w").pack(side="left")
        ttk.Spinbox(bir, from_=1, to=1440, increment=1, textvariable=self.var_bot_interval,
                    width=8, style="A.TSpinbox",
                    command=self.save_bot_config).pack(side="right")

        PillButton(c2d, "ทดสอบส่งข้อความ", self.test_send_telegram, "secondary",
                   width=150, height=32, font=(self.ff, 9, "bold")).pack(anchor="w", padx=14, pady=(0, 6))
        self.lbl_bot_status = tk.Label(c2d, text="", bg=CARD, fg=SUBTLE,
                                       font=(self.ff, 9), justify="left")
        self.lbl_bot_status.pack(anchor="w", padx=14, pady=(0, 12))

        # ===== คอลัมน์ขวา =====
        # ----- ตั้งค่า -----
        c3 = make_card(right, "ตั้งค่า", self.ff)
        self.var_conf = tk.DoubleVar(value=0.85)
        self.var_scan = tk.DoubleVar(value=1.0)
        self.var_cd = tk.DoubleVar(value=3.0)
        self.var_gap = tk.DoubleVar(value=0.5)
        self.var_timeout = tk.DoubleVar(value=0.0)
        self.var_retries = tk.IntVar(value=0)
        self.var_step_cooldown = tk.DoubleVar(value=0.0)
        self.var_clickall = tk.BooleanVar(value=True)
        self.var_scale = tk.BooleanVar(value=False)
        self.var_dbl = tk.BooleanVar(value=False)
        self.var_rand = tk.BooleanVar(value=True)
        self.var_rand_spread = tk.DoubleVar(value=60)

        rs = tk.Frame(c3, bg=CARD); rs.pack(fill="x", padx=16, pady=(10, 4))
        self._lbl(rs, "ความแม่นยำ", width=12, anchor="w").pack(side="left")
        self.lbl_conf = self._lbl(rs, "0.85"); self.lbl_conf.pack(side="right")
        ttk.Scale(rs, from_=0.50, to=0.99, variable=self.var_conf, style="A.Horizontal.TScale",
                  command=lambda v: self.lbl_conf.config(text=f"{float(v):.2f}")
                  ).pack(side="left", fill="x", expand=True, padx=8)

        def spin_row(label, var, lo, hi, inc):
            r = tk.Frame(c3, bg=CARD); r.pack(fill="x", padx=16, pady=2)
            self._lbl(r, label, anchor="w").pack(side="left")
            ttk.Spinbox(r, from_=lo, to=hi, increment=inc, textvariable=var,
                        width=6, style="A.TSpinbox").pack(side="right")

        spin_row("สแกนทุกกี่วินาที", self.var_scan, 0.2, 10, 0.2)
        spin_row("[ลำดับ] หน่วงหลังคลิกแต่ละขั้น (วิ)", self.var_gap, 0, 30, 0.5)
        spin_row("[ลำดับ] รอแต่ละขั้นไม่เกิน (วิ, 0=ตลอด)", self.var_timeout, 0, 120, 1)
        spin_row("[ลำดับ] ลองใหม่หากไม่สำเร็จ (ครั้ง)", self.var_retries, 0, 99, 1)
        spin_row("[ลำดับ] ไม่ทำซ้ำหลังสำเร็จ (วิ, 0=ปิด)", self.var_step_cooldown, 0, 600, 1)
        spin_row("[สแคนทั้งหมด] เว้นคลิกซ้ำจุดเดิม (วิ)", self.var_cd, 0, 60, 0.5)
        spin_row("ขอบเขตการสุ่มตำแหน่ง (% ของรูป)", self.var_rand_spread, 0, 100, 10)

        for text, var in [("สุ่มตำแหน่งคลิกในรูป (กันคลิกจุดเดิมซ้ำ)", self.var_rand),
                          ("[สแกนทั้งหมด] คลิกทุกจุดที่เจอในรอบเดียว", self.var_clickall),
                          ("ดับเบิลคลิก", self.var_dbl),
                          ("ทนต่อรูปขนาดต่างกันเล็กน้อย (ช้าลงนิดหน่อย)", self.var_scale)]:
            tk.Checkbutton(c3, text=text, variable=var, bg=CARD, fg=TEXT,
                           font=(self.ff, 10), activebackground=CARD,
                           selectcolor=CARD).pack(anchor="w", padx=14, pady=1)
        tk.Frame(c3, bg=CARD, height=6).pack()

        # ----- พื้นที่ + พรีเซ็ต -----
        c4 = make_card(right, "พื้นที่สแกน และ พรีเซ็ต", self.ff)
        rr = tk.Frame(c4, bg=CARD); rr.pack(fill="x", padx=16, pady=(10, 4))
        PillButton(rr, "เลือกพื้นที่สแกน", self.select_region, "secondary",
                   width=140, height=34, font=(self.ff, 9, "bold")).pack(side="left")
        PillButton(rr, "สแกนทั้งจอ", self.clear_region, "secondary",
                   width=110, height=34, font=(self.ff, 9, "bold")).pack(side="left", padx=6)
        self.lbl_region = self._lbl(rr, "ทั้งจอ", fg=SUBTLE); self.lbl_region.pack(side="left", padx=4)

        pp = tk.Frame(c4, bg=CARD); pp.pack(fill="x", padx=16, pady=(0, 14))
        PillButton(pp, "บันทึกพรีเซ็ต", self.save_preset_dialog, "secondary",
                   width=130, height=34, font=(self.ff, 9, "bold")).pack(side="left")
        PillButton(pp, "เปิดพรีเซ็ต", self.open_preset_dialog, "secondary",
                   width=110, height=34, font=(self.ff, 9, "bold")).pack(side="left", padx=6)
        PillButton(pp, "ตั้งเป็นค่าเริ่มต้น", self.save_as_default, "secondary",
                   width=150, height=34, font=(self.ff, 9, "bold")).pack(side="left")

        # ----- log -----
        c5 = make_card(right, "บันทึกการทำงาน", self.ff, fill="both", expand=True)
        self.txt = tk.Text(c5, height=5, bg="#fbfbfd", fg=TEXT, bd=0,
                           highlightthickness=0, wrap="word", font=(self.ff, 9),
                           state="disabled", padx=10, pady=8)
        self.txt.pack(fill="both", expand=True, padx=14, pady=(8, 14))

    # ---------------- รายการขั้นตอน ----------------
    def _step_opts_str(self, s):
        """สรุปคุณสมบัติเดี่ยวของขั้น แสดงในคอลัมน์ 'ตัวเลือกเพิ่ม' (ค่าว่าง=ใช้ค่ารวม)"""
        tags = []
        if s.get("type") == "position" and s.get("pos"):
            x, y = s["pos"][0], s["pos"][1]
            tags.append(f"ที่ ({x},{y})")
        if s.get("retries") is not None:
            tags.append(f"ลองใหม่ {s['retries']}")
        if s.get("gap") is not None:
            tags.append(f"หน่วง {s['gap']}s")
        if s.get("timeout") is not None:
            tags.append(f"รอ {s['timeout']}s")
        if s.get("cooldown") is not None:
            tags.append(f"ไม่ซ้ำ {s['cooldown']}s")
        if s.get("require_prev"):
            tags.append("ต้องมีก่อนหน้า")
        if s.get("capture_result"):
            tags.append("บันทึกผล")
        return ", ".join(tags) if tags else "—"

    def refresh_list(self, keep=None):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.steps):
            mode = "ยืดหยุ่น ★" if s.get("flexible") else "ลำดับ"
            opts = self._step_opts_str(s)
            kind = "[ตำแหน่ง] " if s.get("type") == "position" else ""
            self.tree.insert("", "end", iid=str(i),
                             text=f"  {i+1}.  {kind}{s['name']}",
                             values=(s["clicks"], mode, opts))
        if keep is not None and 0 <= keep < len(self.steps):
            self.tree.selection_set(str(keep))
            self.tree.focus(str(keep))

    def _on_step_select(self, _evt=None):
        """โหลดคุณสมบัติของขั้นที่เลือก ลงในช่องคุณสมบัติ (ว่าง = ใช้ค่ารวม)"""
        i = self._sel()
        if i is None:
            return
        s = self.steps[i]
        self.var_step_retries.set("" if s.get("retries") is None else str(s.get("retries")))
        self.var_step_gap.set("" if s.get("gap") is None else str(s.get("gap")))
        self.var_step_timeout.set("" if s.get("timeout") is None else str(s.get("timeout")))
        self.var_step_cd.set("" if s.get("cooldown") is None else str(s.get("cooldown")))
        self.var_step_reqprev.set(bool(s.get("require_prev", False)))
        self.var_step_capture.set(bool(s.get("capture_result", False)))

    def _sel(self):
        s = self.tree.selection()
        return int(s[0]) if s else None

    def add_image(self):
        paths = filedialog.askopenfilenames(title="เลือกรูปตัวอย่าง",
            filetypes=[("รูปภาพ", "*.png *.jpg *.jpeg *.bmp"), ("ทั้งหมด", "*.*")])
        for p in paths:
            img = cv2.imread(p)
            if img is None:
                self.log(f"อ่านไฟล์ไม่ได้: {os.path.basename(p)}")
                continue
            st = self._new_step(os.path.basename(p)); st["img"] = img
            self.steps.append(st)
            self.log(f"เพิ่มขั้น: {os.path.basename(p)}")
        self.refresh_list()

    def capture_template(self):
        if pyautogui is None:
            return
        self.root.withdraw(); self.root.update(); time.sleep(0.3)
        region = RegionSelector(self.root).select()
        self.root.deiconify()
        if not region:
            return
        img = grab_screen(region)
        name = simpledialog.askstring("ตั้งชื่อขั้น", "ตั้งชื่อขั้นนี้:",
                                      initialvalue=f"ขั้นที่ {len(self.steps)+1}") or f"ขั้นที่ {len(self.steps)+1}"
        st = self._new_step(name); st["img"] = img
        self.steps.append(st)
        self.refresh_list()
        self.log(f"จับภาพเป็นขั้น: {name}")

    def capture_position(self):
        """เพิ่มขั้น 'ตำแหน่งตายตัว' — ลากครอบพื้นที่เพื่อบันทึกพิกัดจอ (ไม่จับภาพ)
        ตอนทำงานจะคลิกที่พิกัดนี้เสมอ โดยไม่ตรวจสอบว่ามีรูปตรงกันหรือไม่
        เหมาะกับปุ่มที่ตำแหน่งคงที่แต่เนื้อหาบนปุ่มเปลี่ยนไปมา (เช่น ตัวเลข)"""
        if pyautogui is None:
            return
        self.root.withdraw(); self.root.update(); time.sleep(0.3)
        region = RegionSelector(self.root).select()
        self.root.deiconify()
        if not region:
            return
        l, t, w, h = region
        cx, cy = l + w // 2, t + h // 2
        name = simpledialog.askstring("ตั้งชื่อขั้น", "ตั้งชื่อขั้นนี้ (ตำแหน่งตายตัว):",
                                      initialvalue=f"ตำแหน่ง {len(self.steps)+1}") or f"ตำแหน่ง {len(self.steps)+1}"
        st = self._new_step(name)
        st["type"] = "position"
        st["pos"] = (cx, cy, w, h)
        self.steps.append(st)
        self.refresh_list()
        self.log(f"เพิ่มขั้นตำแหน่งตายตัว: {name} ที่ ({cx},{cy})")

    def remove_image(self):
        i = self._sel()
        if i is None:
            return
        del self.steps[i]
        self.refresh_list()

    def move_up(self):
        i = self._sel()
        if i is None or i == 0:
            return
        self.steps[i-1], self.steps[i] = self.steps[i], self.steps[i-1]
        self.refresh_list(keep=i-1)

    def move_down(self):
        i = self._sel()
        if i is None or i >= len(self.steps)-1:
            return
        self.steps[i+1], self.steps[i] = self.steps[i], self.steps[i+1]
        self.refresh_list(keep=i+1)

    def toggle_flex(self):
        i = self._sel()
        if i is None:
            self.log("เลือกขั้นก่อน แล้วกด 'สลับ ลำดับ/ยืดหยุ่น'")
            return
        self.steps[i]["flexible"] = not self.steps[i].get("flexible")
        self.refresh_list(keep=i)

    def apply_clicks(self):
        i = self._sel()
        if i is None:
            self.log("เลือกขั้นก่อน แล้วกด 'ใช้กับขั้นที่เลือก'")
            return
        self.steps[i]["clicks"] = int(self.var_clicks.get())
        self.refresh_list(keep=i)

    def _new_step(self, name):
        """สร้าง dict ขั้นใหม่พร้อมค่าเริ่มต้น — retries/gap/timeout = None (ใช้ค่ารวม)"""
        return {
            "name": name,
            "type": "image",       # "image" = จับคู่รูป (เดิม) / "position" = คลิกพิกัดตายตัวเสมอ
            "clicks": int(self.var_clicks.get()),
            "flexible": False,
            "retries": None,        # None = ใช้ค่ารวม (step_retries)
            "gap": None,            # None = ใช้ค่ารวม (step_gap)
            "timeout": None,        # None = ใช้ค่ารวม (step_timeout)
            "cooldown": None,      # None = ใช้ค่ารวม (step_cd)
            "require_prev": False,
            "capture_result": False,
            "img": None,
            "pos": None,            # (x, y, w, h) พิกัดจอ — ใช้เมื่อ type == "position"
        }

    def _parse_opt(self, var):
        """อ่านค่าจากช่องคุณสมบัติเดี่ยว: ค่าว่าง -> None, มิฉะนั้น float/int"""
        txt = (var.get() or "").strip()
        if txt == "":
            return None
        try:
            return int(txt)
        except ValueError:
            try:
                return float(txt)
            except ValueError:
                return None

    def apply_step_props(self):
        """บันทึกคุณสมบัติเดี่ยว (ลองใหม่/หน่วง/รอ/ทำต่อเมื่อก่อนหน้าสำเร็จ) ลงขั้นที่เลือก"""
        i = self._sel()
        if i is None:
            self.log("เลือกขั้นก่อน แล้วกด 'บันทึกคุณสมบัติลงขั้นที่เลือก'")
            return
        r = self._parse_opt(self.var_step_retries)
        self.steps[i]["retries"] = (int(r) if r is not None else None)
        self.steps[i]["gap"] = self._parse_opt(self.var_step_gap)
        self.steps[i]["timeout"] = self._parse_opt(self.var_step_timeout)
        self.steps[i]["cooldown"] = self._parse_opt(self.var_step_cd)
        self.steps[i]["require_prev"] = bool(self.var_step_reqprev.get())
        self.steps[i]["capture_result"] = bool(self.var_step_capture.get())
        self.refresh_list(keep=i)
        self.log(f"บันทึกคุณสมบัติขั้น {i+1} แล้ว")

    # ---------------- พื้นที่สแกน ----------------
    def select_region(self):
        if pyautogui is None:
            return
        self.root.withdraw(); self.root.update(); time.sleep(0.3)
        region = RegionSelector(self.root).select()
        self.root.deiconify()
        if region:
            self.region = region
            l, t, w, h = region
            self.lbl_region.config(text=f"{w}x{h} ที่ ({l},{t})")

    def clear_region(self):
        self.region = None
        self.lbl_region.config(text="ทั้งจอ")

    # ---------------- บันทึกผลลัพธ์การเล่น ----------------
    def _toggle_results_section(self):
        if self.var_save_results.get():
            self.results_frame.pack(fill="both", expand=True)
            self.root.after(50, lambda: self.left_scroll.canvas.yview_moveto(1.0))
            if not HAS_OCR:
                messagebox.showwarning("ไม่พบ OCR",
                    "ยังไม่ได้ติดตั้ง pytesseract หรือโปรแกรม Tesseract-OCR\n"
                    "ระบบจะบันทึกได้เฉพาะ Round/เวลา ส่วน Coins/XP จะว่าง")
        else:
            self.results_frame.pack_forget()

    def pick_coins_region(self):
        if pyautogui is None:
            return
        self.root.withdraw(); self.root.update(); time.sleep(0.3)
        region = RegionSelector(self.root).select()
        self.root.deiconify()
        if region:
            self.coins_region = region
            l, t, w, h = region
            self.lbl_coins_region.config(text=f"{w}x{h} ที่ ({l},{t})")

    def pick_xp_region(self):
        if pyautogui is None:
            return
        self.root.withdraw(); self.root.update(); time.sleep(0.3)
        region = RegionSelector(self.root).select()
        self.root.deiconify()
        if region:
            self.xp_region = region
            l, t, w, h = region
            self.lbl_xp_region.config(text=f"{w}x{h} ที่ ({l},{t})")

    def _add_result_row(self, row):
        self.res_tv.insert("", "end", values=(row["round"], row["time_start"], row["time_end"],
                                              row["elapsed"], row["coins"], row["xp"]))
        self.res_tv.see(self.res_tv.get_children()[-1])
        self._update_totals()

    def _update_totals(self):
        coins_sum, xp_sum = sum_results(self.results)
        self.lbl_totals.config(text=f"รวม Coins: {coins_sum:,}    รวม XP: {xp_sum:,}")

    def _init_results_csv(self):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        fname = time.strftime("results_%Y%m%d_%H%M%S.csv")
        self.results_csv_path = os.path.join(RESULTS_DIR, fname)
        with open(self.results_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["Round", "Time start", "Time end", "Time elapsed (s)", "Coins", "XP"])

    def _append_result_csv(self, row):
        if not self.results_csv_path:
            return
        try:
            with open(self.results_csv_path, "a", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow([row["round"], row["time_start"], row["time_end"],
                                        row["elapsed"], row["coins"], row["xp"]])
        except Exception as e:
            self.log(f"บันทึกไฟล์ผลลัพธ์ไม่สำเร็จ: {e}")

    def _capture_result(self):
        """เรียกตอน 'เจอ' ขั้นที่ตั้งจับผลลัพธ์ไว้ (ก่อนคลิก) — OCR Coins/XP แล้วบันทึก 1 แถว"""
        t_end = time.time()
        t_start = self.round_start_time or t_end
        coins = ocr_digits(self.coins_region, self.tesseract_path)
        xp = ocr_digits(self.xp_region, self.tesseract_path)
        self.round_num += 1
        row = {
            "round": self.round_num,
            "time_start": time.strftime("%H:%M:%S", time.localtime(t_start)),
            "time_end": time.strftime("%H:%M:%S", time.localtime(t_end)),
            "elapsed": round(t_end - t_start, 1),
            "coins": coins if coins is not None else "",
            "xp": xp if xp is not None else "",
        }
        self.results.append(row)
        self.round_start_time = t_end
        self.root.after(0, lambda: self._add_result_row(row))
        self._append_result_csv(row)
        self.log(f"บันทึกผล รอบ {row['round']}: Coins={row['coins']} XP={row['xp']} ({row['elapsed']}s)")

    def export_results(self):
        if not self.results:
            messagebox.showwarning("ยังไม่มีข้อมูล", "ยังไม่มีผลลัพธ์ให้ส่งออก"); return
        path = filedialog.asksaveasfilename(title="ส่งออกตารางผลลัพธ์", defaultextension=".csv",
            initialfile="results.csv",
            filetypes=[("CSV", "*.csv"), ("JSON", "*.json"), ("Text", "*.txt")])
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.results, f, ensure_ascii=False, indent=2)
            elif ext == ".txt":
                with open(path, "w", encoding="utf-8") as f:
                    for r in self.results:
                        f.write(f"Round {r['round']}: {r['time_start']} -> {r['time_end']} "
                                f"({r['elapsed']}s)  Coins={r['coins']}  XP={r['xp']}\n")
            else:
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(["Round", "Time start", "Time end", "Time elapsed (s)", "Coins", "XP"])
                    for r in self.results:
                        w.writerow([r["round"], r["time_start"], r["time_end"], r["elapsed"],
                                   r["coins"], r["xp"]])
            self.log(f"ส่งออกผลลัพธ์: {path}")
            messagebox.showinfo("สำเร็จ", "ส่งออกไฟล์แล้ว")
        except Exception as e:
            messagebox.showerror("ส่งออกไม่สำเร็จ", str(e))

    def clear_results(self):
        self.results = []
        self.res_tv.delete(*self.res_tv.get_children())
        self._update_totals()

    # ---------------- หยุดอัตโนมัติ ----------------
    def _tick_auto_stop(self):
        if not self.running or self.stop_at is None:
            return
        remaining = self.stop_at - time.time()
        if remaining <= 0:
            self.lbl_stop_countdown.config(text="")
            self.log("=== หยุดอัตโนมัติ (ครบเวลาที่ตั้งไว้) ===")
            self.stop()
            return
        h, m = format_remaining(remaining)
        stop_clock_str = time.strftime("%H:%M", time.localtime(self.stop_at))
        self.lbl_stop_countdown.config(
            text=f"จะหยุดทำงานในอีก {h} ชม {m} นาที (เวลา {stop_clock_str})")
        self.auto_stop_job = self.root.after(30_000, self._tick_auto_stop)

    # ---------------- ตัวช่วยคำนวณเวลาหยุด ----------------
    def open_stop_calculator(self):
        top = tk.Toplevel(self.root)
        top.title("คำนวณเวลาหยุด")
        top.configure(bg=BG)
        top.resizable(False, False)
        top.transient(self.root)

        avg = compute_avg_round_seconds(self.results)
        var_avg = tk.DoubleVar(value=round(avg, 1) if avg is not None else 0.0)
        var_hearts = tk.IntVar(value=1)

        body = tk.Frame(top, bg=BG); body.pack(padx=18, pady=16)
        r1 = tk.Frame(body, bg=BG); r1.pack(fill="x", pady=4)
        tk.Label(r1, text="ค่าเฉลี่ยต่อรอบ (วินาที)", bg=BG, fg=TEXT,
                 font=(self.ff, 10), anchor="w").pack(side="left")
        ttk.Spinbox(r1, from_=0, to=99999, increment=1, textvariable=var_avg,
                    width=10, style="A.TSpinbox").pack(side="right")

        r2 = tk.Frame(body, bg=BG); r2.pack(fill="x", pady=4)
        tk.Label(r2, text="จำนวนหัวใจ", bg=BG, fg=TEXT,
                 font=(self.ff, 10), anchor="w").pack(side="left")
        ttk.Spinbox(r2, from_=0, to=9999, increment=1, textvariable=var_hearts,
                    width=10, style="A.TSpinbox").pack(side="right")

        lbl_result = tk.Label(body, text="", bg=BG, fg=TEXT,
                              font=(self.ff, 11, "bold"), justify="left")
        lbl_result.pack(fill="x", pady=(10, 12))

        state = {"total_seconds": None}

        def recompute(*_):
            try:
                total_seconds = compute_hearts_estimate(float(var_avg.get()), int(var_hearts.get()))
            except (ValueError, tk.TclError):
                lbl_result.config(text="ค่าต้องไม่ติดลบ")
                state["total_seconds"] = None
                return
            h, m = format_remaining(total_seconds)
            end_clock = time.strftime("%H:%M", time.localtime(time.time() + total_seconds))
            lbl_result.config(text=f"รวม {h} ชม {m} นาที\nจบประมาณเวลา {end_clock}")
            state["total_seconds"] = total_seconds

        def use_this():
            recompute()
            if state["total_seconds"] is None:
                return
            self.var_stop_mode.set("duration")
            self.var_stop_duration.set(round(state["total_seconds"] / 3600.0, 3))
            top.destroy()

        var_avg.trace_add("write", recompute)
        var_hearts.trace_add("write", recompute)

        PillButton(body, "ใช้ค่านี้ตั้งเวลาหยุด", use_this, "primary",
                  width=220, height=36, font=(self.ff, 10, "bold"), bg=BG).pack(fill="x")

        recompute()
        top.grab_set()
        self.root.wait_window(top)

    # ---------------- พรีเซ็ต ----------------
    def collect_preset(self):
        return {
            "version": 4,
            "settings": {
                "confidence": float(self.var_conf.get()),
                "scan_interval": float(self.var_scan.get()),
                "cooldown": float(self.var_cd.get()),
                "step_gap": float(self.var_gap.get()),
                "step_timeout": float(self.var_timeout.get()),
                "step_retries": int(self.var_retries.get()),
                "step_cooldown": float(self.var_step_cooldown.get()),
                "click_all": bool(self.var_clickall.get()),
                "double_click": bool(self.var_dbl.get()),
                "random_click": bool(self.var_rand.get()),
                "random_spread": float(self.var_rand_spread.get()),
                "multiscale": bool(self.var_scale.get()),
                "mode": self.var_mode.get(),
                "loop": bool(self.var_loop.get()),
                "region": list(self.region) if self.region else None,
                "save_results": bool(self.var_save_results.get()),
                "coins_region": list(self.coins_region) if self.coins_region else None,
                "xp_region": list(self.xp_region) if self.xp_region else None,
                "tesseract_path": self.tesseract_path,
            },
            "steps": [{"name": s["name"], "clicks": s["clicks"],
                       "flexible": bool(s.get("flexible")),
                       "type": s.get("type", "image"),
                       "pos": list(s["pos"]) if s.get("pos") else None,
                       "retries": s.get("retries"),        # None = ใช้ค่ารวม
                       "gap": s.get("gap"),                # None = ใช้ค่ารวม
                       "timeout": s.get("timeout"),        # None = ใช้ค่ารวม
                       "cooldown": s.get("cooldown"),      # None = ใช้ค่ารวม
                       "require_prev": bool(s.get("require_prev", False)),
                       "capture_result": bool(s.get("capture_result", False)),
                       "image_b64": img_to_b64(s["img"]) if s.get("img") is not None else None}
                      for s in self.steps],
        }

    def save_preset(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.collect_preset(), f, ensure_ascii=False, indent=2)

    def save_preset_dialog(self):
        if not self.steps:
            messagebox.showwarning("ยังไม่มีขั้นตอน", "เพิ่มขั้นตอนก่อนบันทึก"); return
        path = filedialog.asksaveasfilename(title="บันทึกพรีเซ็ต", defaultextension=".json",
            initialfile="preset.json", filetypes=[("Preset", "*.json")])
        if path:
            self.save_preset(path)
            self.log(f"บันทึกพรีเซ็ต: {path}")
            messagebox.showinfo("สำเร็จ", "บันทึกแล้ว คัดลอกไฟล์นี้ไปเปิดเครื่องอื่นได้เลย")

    def save_as_default(self):
        if not self.steps:
            messagebox.showwarning("ยังไม่มีขั้นตอน", "เพิ่มขั้นตอนก่อนบันทึก"); return
        self.save_preset(DEFAULT_PRESET)
        self.log(f"ตั้งเป็นค่าเริ่มต้น: {DEFAULT_PRESET}")
        messagebox.showinfo("สำเร็จ", "ครั้งต่อไปเปิดโปรแกรมจะโหลดค่านี้อัตโนมัติ\n"
                                      "ส่งทั้งโฟลเดอร์ให้ที่บ้าน เปิดแล้วกดเริ่มได้เลย")

    def open_preset_dialog(self):
        path = filedialog.askopenfilename(title="เปิดพรีเซ็ต", filetypes=[("Preset", "*.json")])
        if path:
            self.load_preset(path)

    def load_preset(self, path, silent=False):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            st = data.get("settings", {})
            self.var_conf.set(st.get("confidence", 0.85))
            self.lbl_conf.config(text=f"{float(st.get('confidence',0.85)):.2f}")
            self.var_scan.set(st.get("scan_interval", 1.0))
            self.var_cd.set(st.get("cooldown", 3.0))
            self.var_gap.set(st.get("step_gap", 0.5))
            self.var_timeout.set(st.get("step_timeout", 0.0))
            self.var_retries.set(st.get("step_retries", 0))
            self.var_step_cooldown.set(st.get("step_cooldown", 0))
            self.var_clickall.set(st.get("click_all", True))
            self.var_dbl.set(st.get("double_click", False))
            self.var_rand.set(st.get("random_click", True))
            self.var_rand_spread.set(st.get("random_spread", 60))
            self.var_scale.set(st.get("multiscale", False))
            self.var_mode.set(st.get("mode", "sequence"))
            self.var_loop.set(st.get("loop", True))
            reg = st.get("region")
            self.region = tuple(reg) if reg else None
            self.lbl_region.config(text=(f"{reg[2]}x{reg[3]} ที่ ({reg[0]},{reg[1]})" if reg else "ทั้งจอ"))

            self.var_save_results.set(st.get("save_results", False))
            self._toggle_results_section()
            creg = st.get("coins_region")
            self.coins_region = tuple(creg) if creg else None
            self.lbl_coins_region.config(text=(f"{creg[2]}x{creg[3]} ที่ ({creg[0]},{creg[1]})" if creg else "ยังไม่เลือก"))
            xreg = st.get("xp_region")
            self.xp_region = tuple(xreg) if xreg else None
            self.lbl_xp_region.config(text=(f"{xreg[2]}x{xreg[3]} ที่ ({xreg[0]},{xreg[1]})" if xreg else "ยังไม่เลือก"))
            self.tesseract_path = st.get("tesseract_path", "")

            self.steps = []
            for s in data.get("steps", []):
                stype = s.get("type", "image")
                img = b64_to_img(s["image_b64"]) if s.get("image_b64") else None
                pos = tuple(s["pos"]) if s.get("pos") else None
                if stype == "image" and img is None:
                    continue   # ขั้นรูปภาพที่ข้อมูลรูปหาย -> ข้าม
                if stype == "position" and pos is None:
                    continue   # ขั้นตำแหน่งที่ไม่มีพิกัด -> ข้าม
                self.steps.append({
                    "name": s.get("name", "ขั้น"),
                    "type": stype,
                    "clicks": int(s.get("clicks", 1)),
                    "flexible": bool(s.get("flexible", False)),
                    "retries": s.get("retries"),            # None = ใช้ค่ารวม
                    "gap": s.get("gap"),                    # None = ใช้ค่ารวม
                    "timeout": s.get("timeout"),            # None = ใช้ค่ารวม
                    "cooldown": s.get("cooldown"),          # None = ใช้ค่ารวม
                    "require_prev": bool(s.get("require_prev", False)),
                    "capture_result": bool(s.get("capture_result", False)),
                    "img": img,
                    "pos": pos,
                })
            self.refresh_list()
            if not silent:
                self.log(f"เปิดพรีเซ็ต: {os.path.basename(path)}  ({len(self.steps)} ขั้น)")
        except Exception as e:
            if not silent:
                messagebox.showerror("เปิดไม่สำเร็จ", str(e))

    # ---------------- Telegram ----------------
    def load_bot_config(self):
        if not os.path.exists(BOT_CONFIG_PATH):
            return
        try:
            with open(BOT_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.var_bot_enabled.set(data.get("enabled", False))
            self.var_bot_token.set(data.get("token", ""))
            self.var_bot_chat_id.set(data.get("chat_id", ""))
            self.var_bot_interval.set(data.get("interval_min", 30))
            self.var_bot_prefix.set(data.get("prefix", ""))
        except Exception as e:
            self.log(f"โหลดค่า Telegram ไม่สำเร็จ: {e}")

    def save_bot_config(self):
        data = {
            "enabled": bool(self.var_bot_enabled.get()),
            "token": self.var_bot_token.get(),
            "chat_id": self.var_bot_chat_id.get(),
            "interval_min": int(self.var_bot_interval.get()),
            "prefix": self.var_bot_prefix.get(),
        }
        try:
            with open(BOT_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"บันทึกค่า Telegram ไม่สำเร็จ: {e}")

    def _send_telegram_message(self, text):
        """เรียกจาก background thread เท่านั้น (ไม่บล็อก UI thread) คืน (สำเร็จหรือไม่, ข้อความ)"""
        token = self.var_bot_token.get().strip()
        chat_id = self.var_bot_chat_id.get().strip()
        if not token or not chat_id:
            return False, "ยังไม่ได้ตั้งค่า Token หรือ Chat ID"
        try:
            resp = requests.post(build_telegram_url(token),
                                 json={"chat_id": chat_id, "text": text},
                                 timeout=10)
            if resp.ok:
                return True, "ส่งสำเร็จ"
            return False, f"ส่งไม่สำเร็จ (HTTP {resp.status_code})"
        except requests.RequestException as e:
            return False, f"ส่งไม่สำเร็จ: {e}"

    def test_send_telegram(self):
        if not HAS_REQUESTS:
            messagebox.showerror("ใช้งานไม่ได้", "ติดตั้งไลบรารี requests ก่อน"); return
        self.save_bot_config()

        def worker():
            prefix = self.var_bot_prefix.get().strip()
            test_text = f"{prefix}\nทดสอบการเชื่อมต่อจาก Image Clicker" if prefix else "ทดสอบการเชื่อมต่อจาก Image Clicker"
            ok, msg = self._send_telegram_message(test_text)
            self.root.after(0, lambda: self.lbl_bot_status.config(
                text=msg, fg=(GREEN if ok else DANGER)))
            self.root.after(0, lambda: self.log(f"Telegram ทดสอบ: {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    def _start_telegram_sender(self):
        if not HAS_REQUESTS or not self.var_bot_enabled.get():
            return
        if self._telegram_thread is not None and self._telegram_thread.is_alive():
            return
        self._telegram_stop_flag = threading.Event()
        self._telegram_thread = threading.Thread(target=self._telegram_loop, daemon=True)
        self._telegram_thread.start()

    def _stop_telegram_sender(self):
        if self._telegram_stop_flag is not None:
            self._telegram_stop_flag.set()

    def _telegram_loop(self):
        stop_flag = self._telegram_stop_flag
        while self.running and not stop_flag.is_set():
            interval_s = max(60, int(self.var_bot_interval.get()) * 60)
            waited = 0
            while waited < interval_s:
                if not self.running or stop_flag.is_set():
                    return
                time.sleep(min(5, interval_s - waited))
                waited += 5
            if not self.running or stop_flag.is_set():
                return
            coins_sum, xp_sum = sum_results(list(self.results))
            prefix = self.var_bot_prefix.get().strip()
            text = format_telegram_report(coins_sum, xp_sum, self.round_num, prefix)
            ok, msg = self._send_telegram_message(text)
            self.root.after(0, lambda ok=ok, msg=msg: self.lbl_bot_status.config(
                text=msg, fg=(GREEN if ok else DANGER)))
            if not ok:
                self.root.after(0, lambda msg=msg: self.log(f"Telegram ส่งไม่สำเร็จ: {msg}"))

    # ---------------- เริ่ม/หยุด ----------------
    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self):
        if pyautogui is None:
            return
        if not self.steps:
            messagebox.showwarning("ยังไม่มีขั้นตอน", "เพิ่มอย่างน้อย 1 ขั้นก่อน"); return

        self.stop_at = None
        if self.var_stop_enabled.get():
            now = time.time()
            try:
                if self.var_stop_mode.get() == "duration":
                    hours = float(self.var_stop_duration.get())
                    self.stop_at = compute_stop_at_from_duration(now, hours)
                else:
                    hh, mm = parse_hhmm(self.var_stop_clock.get())
                    self.stop_at = compute_stop_at_from_clock(now, hh, mm)
            except (ValueError, tk.TclError) as e:
                messagebox.showerror("เวลาไม่ถูกต้อง", str(e))
                return

        self.cfg = {
            "conf": float(self.var_conf.get()),
            "scan": float(self.var_scan.get()),
            "cooldown": float(self.var_cd.get()),
            "gap": float(self.var_gap.get()),
            "timeout": float(self.var_timeout.get()),
            "retries": int(self.var_retries.get()),
            "step_cd": float(self.var_step_cooldown.get()),
            "click_all": bool(self.var_clickall.get()),
            "dbl": bool(self.var_dbl.get()),
            "rand": bool(self.var_rand.get()),
            "rand_spread": float(self.var_rand_spread.get()),
            "scales": (0.85, 0.9, 1.0, 1.1, 1.15) if self.var_scale.get() else (1.0,),
            "mode": self.var_mode.get(),
            "loop": bool(self.var_loop.get()),
            "region": self.region,
            "steps": [dict(s) for s in self.steps],
            "save_results": bool(self.var_save_results.get()),
        }
        self.running = True
        self.recent_clicks = []
        self.last_done = {}   # step_index -> time.time() เมื่อสำเร็จครั้งล่าสุด (ใช้ cooldown)

        self.results = []
        self.round_num = 0
        self.round_start_time = time.time()
        self.results_csv_path = None
        if self.cfg["save_results"]:
            self.res_tv.delete(*self.res_tv.get_children())
            self._update_totals()
            self._init_results_csv()
            self.log(f"บันทึกผลลัพธ์ลงไฟล์: {self.results_csv_path}")

        self.btn_start.set_state(text="หยุด  (F8)", kind="danger")
        self.log(f"=== เริ่มทำงาน (โหมด: {'ตามลำดับ' if self.cfg['mode']=='sequence' else 'สแกนทั้งหมด'}) ===")
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

        if self.stop_at is not None:
            self._tick_auto_stop()
        if self.var_bot_enabled.get():
            self._start_telegram_sender()

    def stop(self):
        self.running = False
        if self.auto_stop_job is not None:
            self.root.after_cancel(self.auto_stop_job)
            self.auto_stop_job = None
        self._stop_telegram_sender()
        self.btn_start.set_state(text="เริ่มทำงาน  (F8)", kind="primary")
        self.log("=== หยุดทำงาน ===")

    # ---------------- ลูปทำงาน ----------------
    def _offset(self):
        r = self.cfg["region"]
        return (r[0], r[1]) if r else (0, 0)

    def _loop(self):
        try:
            if self.cfg["mode"] == "sequence":
                self._run_sequence()
            else:
                self._run_scan_all()
        except pyautogui.FailSafeException:
            self.log("หยุดฉุกเฉิน (เมาส์ชนมุมจอ)")
        except Exception as e:
            self.log(f"ผิดพลาด: {e}")
        self.running = False
        self.root.after(0, lambda: self.btn_start.set_state(text="เริ่มทำงาน  (F8)", kind="primary"))

    def _run_sequence(self):
        c = self.cfg
        offx, offy = self._offset()
        steps = c["steps"]
        groups = build_groups([s.get("flexible", False) for s in steps])
        gi = 0
        prev_ok = True   # สถานะขั้นก่อนหน้า (ขั้นแรกถือว่าก่อนหน้า "สำเร็จ" เสมอ)
        while self.running:
            gtype, idxs = groups[gi]
            lead = steps[idxs[0]]   # ขั้นนำของกลุ่ม (ใช้ตรวจ require_prev ของกลุ่ม)

            # --- ทำต่อเมื่อขั้นก่อนหน้าสำเร็จ ---
            if lead.get("require_prev") and not prev_ok:
                names = " / ".join(steps[k]["name"] for k in idxs)
                self.log(f"⏭  ข้าม '{names}' เพราะขั้นก่อนหน้าไม่สำเร็จ (ตั้ง 'ทำต่อเมื่อก่อนหน้าสำเร็จ')")
                prev_ok = False   # ยังคง cascade: ขั้นถัดไปที่ตั้ง require_prev ก็ถูกข้ามด้วย
            elif gtype == "strict":
                prev_ok = self._do_strict(steps[idxs[0]], idxs[0], offx, offy)
            else:
                prev_ok = self._do_priority(steps, idxs, offx, offy)

            gi += 1
            if gi >= len(groups):
                if c["loop"]:
                    gi = 0
                    prev_ok = True   # เริ่มรอบใหม่ -> รีเซ็ตสถานะก่อนหน้า
                    self.log("--- ครบทุกขั้น เริ่มรอบใหม่ ---")
                else:
                    self.log("=== ทำครบทุกขั้นแล้ว จบ ===")
                    break

    def _step_val(self, step, key, default):
        """ค่าเฉพาะของขั้น (ถ้ามี) ไม่งั้นใช้ค่ารวม — None = ใช้ค่ารวม"""
        v = step.get(key)
        return default if v is None else v

    def _in_step_cd(self, step_idx, step, num):
        """ตรวจว่าขั้นนี้อยู่ในช่วง cooldown หรือยัง (หลังสำเร็จ)"""
        c = self.cfg
        cd = self._step_val(step, "cooldown", c["step_cd"])
        if cd <= 0:
            return False
        last = self.last_done.get(step_idx)
        if last is None:
            return False
        if (time.time() - last) < cd:
            remain = cd - (time.time() - last)
            self.log(f"ขั้น {num+1}: {step['name']} อยู่ใน cooldown อีก {remain:.1f} วิ -> ข้าม")
            return True
        return False

    def _do_strict(self, step, num, offx, offy):
        """ทำขั้นลำดับ 1 ขั้น คืน True ถ้าคลิกสำเร็จ, False ถ้าหาไม่เจอหลังพยายามหมด
        - รอแต่ละครั้งไม่เกิน timeout (เฉพาะขั้น หรือค่ารวม)
        - ลองใหม่ได้ 'retries' ครั้ง (เฉพาะขั้น หรือค่ารวม)
        - หน่วงหลังคลิก gap วินาที (เฉพาะขั้น หรือค่ารวม)
        - cooldown: ไม่ทำซ้ำภายใน N วินาทีหลังสำเร็จ (เฉพาะขั้น หรือค่ารวม)"""
        c = self.cfg
        # --- cooldown check ---
        if self._in_step_cd(num, step, num):
            return True    # ถือว่า "สำเร็จ" (เพราะเคยทำสำเร็จแล้ว แค่รอ cooldown)
        timeout = self._step_val(step, "timeout", c["timeout"])
        retries = self._step_val(step, "retries", c["retries"])
        gap = self._step_val(step, "gap", c["gap"])
        attempts = int(retries) + 1   # ลองครั้งแรก + ลองใหม่ retries ครั้ง
        for att in range(attempts):
            if not self.running:
                return False
            label = f"ขั้น {num+1}: {step['name']}" + (f"  (ลองครั้ง {att+1}/{attempts})" if attempts > 1 else "")
            self.log(f"กำลังหา {label}")
            t0 = time.time()
            while self.running:
                m = self._find_step_matches(step, c)
                if m:
                    if step.get("capture_result") and c.get("save_results"):
                        self._capture_result()
                    x, y = self._resolve_click_point(step, m[0], offx, offy)
                    self._do_click(x, y, step["clicks"])
                    self.log(f"ขั้น {num+1} คลิกที่ ({x},{y}) x{step['clicks']}")
                    self.last_done[num] = time.time()   # บันทึกเวลาสำเร็จ (สำหรับ cooldown)
                    time.sleep(gap)
                    return True
                if timeout > 0 and (time.time() - t0) > timeout:
                    break   # หมดเวลาครั้งนี้ -> ลองใหม่ (ถ้าเหลือ)
                time.sleep(c["scan"])
            if att < attempts - 1:
                self.log(f"  ขั้น {num+1} หาไม่เจอใน {timeout:.0f} วิ -> ลองใหม่")
        self.log(f"ขั้น {num+1} ล้มเหลว หลังพยายาม {attempts} ครั้ง -> ข้าม")
        return False

    def _do_priority(self, steps, idxs, offx, offy):
        """กลุ่มยืดหยุ่น: เจออันไหนก่อนคลิกอันนั้น คืน True ถ้าคลิกครบทุกขั้นในกลุ่ม
        - ขั้นที่อยู่ใน cooldown จะถูกข้าม (ถือว่าสำเร็จไปแล้ว)"""
        c = self.cfg
        names = " / ".join(steps[k]["name"] for k in idxs)
        self.log(f"กลุ่มยืดหยุ่น: {names}  (เจออันไหนก่อนคลิกอันนั้น)")
        pending = list(idxs)            # ลำดับใน list = ลำดับความสำคัญ
        # --- ข้ามขั้นที่อยู่ใน cooldown ---
        for k in list(pending):
            if self._in_step_cd(k, steps[k], k):
                pending.remove(k)       # cooldown = ถือว่าเคยสำเร็จแล้ว
        if not pending:
            return True                # ทุกขั้นในกลุ่มอยู่ cooldown ทั้งหมด = สำเร็จ
        t0 = time.time()
        while self.running and pending:
            clicked = False
            for k in list(pending):     # ไล่ตามความสำคัญ คลิกตัวแรกที่เจอ
                m = self._find_step_matches(steps[k], c)
                if m:
                    if steps[k].get("capture_result") and c.get("save_results"):
                        self._capture_result()
                    x, y = self._resolve_click_point(steps[k], m[0], offx, offy)
                    self._do_click(x, y, steps[k]["clicks"])
                    gap = self._step_val(steps[k], "gap", c["gap"])   # หน่วงตามขั้นนั้น
                    self.log(f"  -> เจอ '{steps[k]['name']}' คลิกที่ ({x},{y}) x{steps[k]['clicks']}")
                    self.last_done[k] = time.time()   # บันทึกเวลาสำเร็จ (สำหรับ cooldown)
                    pending.remove(k)
                    time.sleep(gap)
                    clicked = True
                    t0 = time.time()
                    break
            if not clicked:
                if c["timeout"] > 0 and (time.time() - t0) > c["timeout"]:
                    self.log(f"  กลุ่มยืดหยุ่นเหลือ {len(pending)} อันที่หาไม่เจอ -> ข้าม")
                    return len(pending) == 0
                time.sleep(c["scan"])
        return len(pending) == 0

    def _run_scan_all(self):
        c = self.cfg
        offx, offy = self._offset()
        while self.running:
            hits = []
            screen = grab_screen(c["region"])
            for step in c["steps"]:
                for match in self._find_step_matches(step, c, screen=screen):
                    x, y = self._resolve_click_point(step, match, offx, offy)
                    hits.append((x, y, step["clicks"]))
            if hits:
                if not c["click_all"]:
                    hits = hits[:1]
                now = time.time()
                for (x, y, clk) in hits:
                    if self._in_cooldown(x, y, c["cooldown"], now):
                        continue
                    self._do_click(x, y, clk)
                    self.recent_clicks.append((x, y, time.time()))
                    self.log(f"คลิกที่ ({x},{y}) x{clk}")
            cutoff = time.time() - max(c["cooldown"], 1)
            self.recent_clicks = [r for r in self.recent_clicks if r[2] >= cutoff]
            time.sleep(c["scan"])

    def _in_cooldown(self, x, y, cooldown, now, tol=15):
        if cooldown <= 0:
            return False
        return any(abs(px-x) <= tol and abs(py-y) <= tol and (now-pt) < cooldown
                   for (px, py, pt) in self.recent_clicks)

    def _find_step_matches(self, step, c, screen=None):
        """คืนรายการ match ของขั้น — ขั้น 'position' คืนพิกัดที่บันทึกไว้เสมอ (ไม่ตรวจจับภาพ)
        ขั้น 'image' หาโดยจับคู่รูปตามปกติ (ใช้ screen ที่ส่งมาถ้ามี กันจับภาพจอซ้ำ)"""
        if step.get("type") == "position":
            pos = step.get("pos")
            return [pos] if pos else []
        scr = screen if screen is not None else grab_screen(c["region"])
        return find_matches(scr, step["img"], c["conf"], c["scales"])

    def _resolve_click_point(self, step, match, offx, offy):
        """แปลง match เป็นพิกัดคลิกจริง — ขั้น 'position' ใช้พิกัดจอตรง ๆ (ไม่บวก offset ของพื้นที่สแกน
        เพราะบันทึกมาจากพิกัดจอเต็มอยู่แล้ว) ขั้น 'image' บวก offset ของพื้นที่สแกนตามปกติ"""
        if step.get("type") == "position":
            return self._target_point_absolute(match)
        return self._target_point(match, offx, offy)

    def _target_point_absolute(self, match):
        """คืนพิกัดคลิกสำหรับขั้นตำแหน่งตายตัว — คลิกที่จุดที่บันทึกไว้เป๊ะ ๆ เสมอ
        (ไม่สุ่มตำแหน่งแม้เปิดตัวเลือก 'สุ่มตำแหน่งคลิก' เพราะจุดประสงค์ของขั้นนี้คือความแม่นยำ
        ถ้าสุ่มตามขนาดกรอบที่ลาก ผู้ใช้ที่ลากกรอบกว้าง ๆ จะโดนคลิกไกลจากปุ่มจริงได้)"""
        cx, cy, _w, _h = match
        return cx, cy

    def _target_point(self, match, offx, offy):
        """คืนพิกัดที่จะคลิก ถ้าเปิดสุ่ม จะสุ่มจุดภายในกรอบรูป (ไม่คลิกกึ่งกลางเป๊ะ)"""
        cx, cy, w, h = match
        if self.cfg.get("rand"):
            spread = self.cfg.get("rand_spread", 60)   # % ของขนาดรูป
            rx = int(w * spread / 200)                 # ครึ่งช่วงแกน x
            ry = int(h * spread / 200)
            if rx > 0:
                cx += random.randint(-rx, rx)
            if ry > 0:
                cy += random.randint(-ry, ry)
        return cx + offx, cy + offy

    def _do_click(self, x, y, n):
        n = max(1, int(n))
        if self.cfg.get("dbl"):
            for _ in range(n):
                pyautogui.doubleClick(x, y); time.sleep(0.05)
        else:
            pyautogui.click(x, y, clicks=n, interval=0.05)

    # ---------------- log ----------------
    def log(self, msg):
        print(time.strftime("[%H:%M:%S] ") + msg)
        def _append():
            self.txt.config(state="normal")
            self.txt.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
            self.txt.see("end")
            self.txt.config(state="disabled")
        try:
            self.root.after(0, _append)
        except Exception:
            pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
