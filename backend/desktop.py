"""Modern local Windows control panel. Only this UI can approve a screen."""
import ctypes
import queue
import sys
import threading
import tkinter as tk
import winreg
from concurrent.futures import Future
from pathlib import Path
from tkinter import ttk

import mss
from PIL import Image, ImageTk
import pystray
import qrcode

from .security import PairingCode


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
BG = "#101820"
SIDEBAR = "#0b131a"
CARD = "#17222c"
CARD_DARK = "#0f1820"
LINE = "#35434d"
TEXT = "#edf3f5"
MUTED = "#9eafb9"
MINT = "#a1e2ce"
MINT_DARK = "#112b27"
RED = "#bd2336"
AMBER = "#d59635"
GREEN = "#27805d"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SETTINGS_KEY = r"Software\PocketPC"
WINDOW_ICON_HANDLES = {}

HE = {
    "Your screen, privately within reach": "המסך שלך, פרטי ובהישג יד",
    "TAILSCALE ONLY": "חיבור פרטי",
    "●  NOT SHARING": "●  לא משתף",
    "PRIVATE PHONE CONNECTION": "חיבור פרטי לטלפון",
    "Open this address in your browser": "פתח את הכתובת בדפדפן בטלפון",
    "PAIRING CODE": "קוד צימוד",
    "SCAN & CONNECT": "סרוק והתחבר",
    "DISPLAY TO SHARE": "מסך לשיתוף",
    "Waiting for a pairing request. Codes expire after five minutes.": "ממתין לבקשת צימוד. תוקף הקוד הוא חמש דקות.",
    "APPROVE SELECTED DISPLAY": "אישור המסך שנבחר",
    "ALLOW VIEW + MOUSE": "אפשר צפייה ושליטה בעכבר",
    "DENY": "דחייה",
    "STOP SHARING": "הפסקת שיתוף",
    "◈  Encrypted with WebRTC + Tailscale     ·     Mouse control requires separate approval": "◈  חיבור מוצפן ופרטי     ·     שליטה בעכבר דורשת אישור נפרד",
    "Settings": "הגדרות",
    "Choose how PocketPC behaves on this Windows PC.": "בחר כיצד התוכנה תפעל במחשב הזה.",
    "Language": "שפה",
    "Language changes after PocketPC restarts.": "השפה תוחל לאחר הפעלה מחדש של התוכנה.",
    "Language saved. Restart PocketPC to apply it.": "השפה נשמרה. הפעל מחדש את התוכנה כדי להחיל אותה.",
    "Start PocketPC with Windows": "הפעלה אוטומטית עם המחשב",
    "PocketPC starts ready, but never shares a screen until you approve.": "התוכנה תופעל ותהיה מוכנה, אך המסך לא ישותף ללא אישורך.",
    "Adaptive screen quality": "איכות שידור אוטומטית",
    "Automatically balances clarity and smoothness from 720p to 1080p.\nYou can choose a fixed quality from Settings on your phone.": "האיכות מותאמת אוטומטית בין 720 ל-1080.\nבטלפון ניתן לבחור איכות קבועה.",
    "12–20 FPS  ·  encrypted WebRTC  ·  up to 8 Mbps": "12–20 תמונות בשנייה  ·  חיבור מוצפן  ·  עד 8 מגה־ביט",
    "Closing the main window keeps PocketPC available in the system tray.\nUse the tray menu to reopen, stop sharing, or quit.": "סגירת החלון הראשי משאירה את התוכנה פעילה במגש המערכת.\nדרך סמל המגש ניתן לפתוח, לעצור שיתוף או לצאת.",
    "DONE": "סיום",
    "APPLY & RESTART": "החל והפעל מחדש",
    "Connection Assistant": "עוזר החיבור",
    "Check the private network, video path and performance engine.": "בדוק את הרשת הפרטית, נתיב הווידאו ומנוע הביצועים.",
    "Run diagnostics": "הפעל בדיקה",
    "Checking PocketPC…": "בודק את PocketPC…",
    "Run a check to confirm everything is ready.": "הפעל בדיקה כדי לוודא שהכול מוכן.",
    "Tailscale": "Tailscale",
    "Private HTTPS": "HTTPS פרטי",
    "WebRTC video": "וידאו WebRTC",
    "Capture engine": "מנוע צילום",
    "Video encoder": "מקודד וידאו",
    "Security": "אבטחה",
    "Connected to the private tailnet": "מחובר לרשת הפרטית",
    "Private HTTPS route is responding": "נתיב ה-HTTPS הפרטי פעיל",
    "WebRTC is ready; no active viewer": "WebRTC מוכן; אין צופה מחובר",
    "DXGI Desktop Duplication is ready": "מנוע DXGI מוכן",
    "DXGI unavailable; MSS fallback will be used": "DXGI אינו זמין; ייעשה שימוש במנוע החלופי",
    "NVIDIA NVENC is ready": "מקודד NVIDIA NVENC מוכן",
    "Software H.264 is active": "מקודד H.264 בתוכנה פעיל",
    "View-only; every new session requires Windows approval": "צפייה בלבד; כל חיבור חדש דורש אישור במחשב",
    "Viewing and optional mouse control require explicit Windows approval": "צפייה ושליטה אופציונלית בעכבר דורשות אישור מפורש ב-Windows",
    "Open PocketPC": "פתיחת PocketPC",
    "Stop sharing": "הפסקת שיתוף",
    "Quit PocketPC": "יציאה מ-PocketPC",
    "PocketPC is still ready. Open it from the tray at any time.": "PocketPC עדיין מוכן. ניתן לפתוח אותו ממגש המערכת בכל עת.",
    "PocketPC will start quietly when you sign in to Windows.": "PocketPC יופעל בשקט בעת הכניסה ל-Windows.",
    "Automatic startup is off. Use the desktop icon when you need PocketPC.": "הפעלה אוטומטית כבויה. השתמש בסמל בשולחן העבודה בעת הצורך.",
    "Windows could not change the startup setting. Try again from your user account.": "Windows לא הצליח לשנות את הגדרת ההפעלה. נסה שוב מחשבון המשתמש שלך.",
    "Sharing is active. You may minimize this window and restore it from the taskbar to stop.": "השיתוף פעיל. ניתן למזער את החלון ולשחזר אותו משורת המשימות כדי לעצור.",
    "●  STOPPED — NOT SHARING": "●  הופסק — לא משתף",
    "The approved phone reconnected automatically.": "הטלפון המאושר התחבר מחדש אוטומטית.",
    "Connection interrupted. The approved phone may reconnect automatically for up to five minutes.": "החיבור נקטע. הטלפון המאושר יכול להתחבר מחדש אוטומטית במשך עד חמש דקות.",
    "Session ended. Every new connection requires your approval.": "ההפעלה הסתיימה. כל חיבור חדש דורש את אישורך.",
    "Mouse control is active for this approved session. Keyboard and files remain blocked.": "שליטה בעכבר פעילה להפעלה המאושרת. המקלדת והקבצים נשארים חסומים.",
    "Input control ended. Screen viewing remains active.": "שליטת הקלט הסתיימה. הצפייה במסך נשארה פעילה.",
    "Screen sharing": "שיתוף מסך",
    "Share your screen": "שתף את המסך שלך",
    "Connect your phone": "חבר את הטלפון שלך",
    "Private connection": "חיבור פרטי",
    "Session controls": "בקרת השיתוף",
    "Connection check": "בדיקת חיבור",
    "Open diagnostics": "פתח אבחון",
    "Ready for a secure connection": "מוכן לחיבור מאובטח",
}


def _colorref(hex_color):
    """Convert #RRGGBB to the BGR COLORREF used by Windows DWM."""
    red, green, blue = (int(hex_color[index:index + 2], 16) for index in (1, 3, 5))
    return red | (green << 8) | (blue << 16)


def use_dark_windows_frame(root):
    """Make the native Windows 11 title bar and border match the app."""
    if sys.platform != "win32":
        return
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    enabled = ctypes.c_int(1)
    for attribute in (20, 19):  # immersive dark mode; 19 supports older Windows builds
        try:
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
            ) == 0:
                break
        except OSError:
            pass
    for attribute, color in ((34, BG), (35, BG), (36, TEXT)):
        value = ctypes.c_int(_colorref(color))
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
        except OSError:
            pass


def use_native_windows_icon(root, icon_path):
    """Assign explicit small and large HICONs so Windows never scales one frame."""
    if sys.platform != "win32" or not icon_path.is_file():
        return
    root.update_idletasks()
    user32 = ctypes.windll.user32
    user32.GetParent.restype = ctypes.c_void_p
    user32.LoadImageW.argtypes = (
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    )
    user32.LoadImageW.restype = ctypes.c_void_p
    hwnd = user32.GetParent(root.winfo_id())
    small_size = user32.GetSystemMetrics(49)  # SM_CXSMICON
    large_size = user32.GetSystemMetrics(11)  # SM_CXICON
    handles = []
    for role, size in ((0, small_size), (1, large_size)):
        handle = user32.LoadImageW(None, str(icon_path), 1, size, size, 0x10)
        if handle:
            user32.SendMessageW(hwnd, 0x80, role, handle)  # WM_SETICON
            handles.append(handle)
    if handles:
        WINDOW_ICON_HANDLES[hwnd] = handles


def keep_dark_windows_frame(root):
    """Reapply DWM colors after Windows maps or reactivates the native frame."""
    pending = {"job": None}

    def schedule(_event=None):
        if pending["job"] is not None:
            root.after_cancel(pending["job"])
        pending["job"] = root.after(50, apply)

    def apply():
        pending["job"] = None
        if root.winfo_exists() and root.state() != "withdrawn":
            use_dark_windows_frame(root)

    root.bind("<Map>", schedule, add="+")
    root.bind("<FocusIn>", schedule, add="+")
    schedule()


class Desktop:
    def _load_language(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as key:
                language, _ = winreg.QueryValueEx(key, "Language")
            return "he" if language == "he" else "en"
        except OSError:
            return "en"

    def _save_language(self, language):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as key:
            winreg.SetValueEx(key, "Language", 0, winreg.REG_SZ, language)

    def raw_t(self, text):
        """Translate for native Windows surfaces that already implement BiDi."""
        return HE.get(text, text) if self.language == "he" else text

    def visual_hebrew(self, text):
        """Tk on Windows handles Hebrew glyph order; alignment is applied separately."""
        return text

    def t(self, text):
        translated = self.raw_t(text)
        return self.visual_hebrew(translated) if self.language == "he" else translated

    def __init__(self, root, url):
        self.root = root
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.code = PairingCode()
        self.current = None
        self.approval = None
        self.mouse_requested = False
        self.on_stop = lambda: None
        self.on_restart = lambda: None
        self.url = url
        self.tray = None
        self.tray_hint_shown = False
        self.quitting = False
        self.settings_window = None
        self.language = self._load_language()
        self.diagnostics_provider = lambda: {}
        self.text_anchor = "e" if self.language == "he" else "w"
        self.text_justify = "right" if self.language == "he" else "left"

        root.title("PocketPC")
        root.geometry("940x650")
        root.minsize(860, 610)
        root.configure(bg=BG)
        root.attributes("-topmost", False)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.autostart = tk.BooleanVar(master=root, value=self._autostart_enabled())
        icon_file = ROOT / "assets" / "pocketpc.ico"
        if icon_file.is_file():
            root.iconbitmap(default=str(icon_file))
            root.after(100, lambda: use_native_windows_icon(root, icon_file))
            root.after(1000, lambda: use_native_windows_icon(root, icon_file))
        icon_path = ROOT / "assets" / "pocketpc-icon-64.png"
        if icon_path.is_file():
            # Used inside the window only. The native title/taskbar icon comes
            # from the multi-size ICO so Windows can select a crisp frame.
            self.icon = tk.PhotoImage(file=icon_path)
        keep_dark_windows_frame(root)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "PocketPC.TCombobox", fieldbackground=CARD_DARK, background=CARD_DARK,
            foreground=TEXT, arrowcolor=MINT, bordercolor=LINE, lightcolor=LINE,
            darkcolor=LINE, padding=9,
        )
        style.map(
            "PocketPC.TCombobox",
            fieldbackground=[("readonly", CARD_DARK), ("disabled", CARD)],
            foreground=[("readonly", TEXT), ("disabled", MUTED)],
            selectbackground=[("readonly", CARD_DARK)],
            selectforeground=[("readonly", TEXT)],
        )

        app_shell = tk.Frame(root, bg=BG)
        app_shell.pack(fill="both", expand=True)

        sidebar = tk.Frame(app_shell, bg=SIDEBAR, width=210, padx=20, pady=22)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill="x", pady=(0, 30))
        if hasattr(self, "icon"):
            tk.Label(brand, image=self.icon, bg=SIDEBAR).pack(anchor="w")
        tk.Label(brand, text="PocketPC", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(8, 0))
        tk.Label(
            brand, text=self.t("Your screen, privately within reach"), bg=SIDEBAR,
            fg=MUTED, font=("Segoe UI", 8), wraplength=165, justify="left",
        ).pack(anchor="w", pady=(3, 0))

        tk.Label(
            sidebar, text="▣   " + self.t("Screen sharing"), bg=MINT_DARK, fg=MINT,
            font=("Segoe UI", 10, "bold"), padx=12, pady=11, anchor="w",
            highlightthickness=1, highlightbackground="#24433d",
        ).pack(fill="x")
        tk.Button(
            sidebar, text="⚙   " + self.t("Settings"), command=self.show_settings,
            relief="flat", bd=0, bg=SIDEBAR, fg=MUTED, activebackground=CARD,
            activeforeground=TEXT, font=("Segoe UI", 10), padx=12, pady=11, anchor="w",
        ).pack(fill="x", pady=(6, 0))
        sidebar_footer = tk.Frame(sidebar, bg=SIDEBAR)
        sidebar_footer.pack(side="bottom", fill="x")
        tk.Label(sidebar_footer, text="●  " + self.t("TAILSCALE ONLY"), bg=SIDEBAR, fg=MINT, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Label(
            sidebar_footer, text=self.t("◈  Encrypted with WebRTC + Tailscale     ·     Mouse control requires separate approval"),
            bg=SIDEBAR, fg="#657985", font=("Segoe UI", 7), wraplength=165, justify="left",
        ).pack(anchor="w", pady=(5, 0))

        main = tk.Frame(app_shell, bg=BG, padx=28, pady=24)
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, bg=BG)
        header.pack(fill="x")
        header_copy = tk.Frame(header, bg=BG)
        header_copy.pack(side="left")
        tk.Label(header_copy, text=self.t("Share your screen"), bg=BG, fg=TEXT, font=("Segoe UI", 20, "bold")).pack(anchor=self.text_anchor)
        tk.Label(
            header_copy, text=self.t("Ready for a secure connection"), bg=BG,
            fg=MUTED, font=("Segoe UI", 9),
        ).pack(anchor=self.text_anchor, pady=(3, 0))

        workspace = tk.Frame(main, bg=BG)
        workspace.pack(fill="both", expand=True, pady=(20, 0))

        connection = tk.Frame(workspace, bg=CARD, padx=20, pady=18, highlightthickness=1, highlightbackground=LINE)
        connection.pack(side="left", fill="both", expand=True, padx=(0, 9))
        tk.Label(connection, text=self.t("Connect your phone"), bg=CARD, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(anchor=self.text_anchor)
        tk.Label(connection, text=self.t("Open this address in your browser"), bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(anchor=self.text_anchor, pady=(4, 10))
        address = tk.Entry(
            connection, font=("Cascadia Mono", 10), bg=CARD_DARK, fg=TEXT,
            readonlybackground=CARD_DARK, relief="flat", highlightthickness=1,
            highlightbackground=LINE, highlightcolor=MINT,
        )
        address.insert(0, url)
        address.configure(state="readonly")
        address.pack(fill="x", ipady=8)

        code_row = tk.Frame(connection, bg=CARD)
        code_row.pack(fill="both", expand=True, pady=(20, 0))
        code_copy = tk.Frame(code_row, bg=CARD)
        code_copy.pack(side="left", anchor="n")
        tk.Label(code_copy, text=self.t("PAIRING CODE"), bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.code_text = tk.StringVar()
        tk.Label(code_copy, textvariable=self.code_text, bg=CARD, fg=TEXT, font=("Cascadia Mono", 25, "bold")).pack(anchor="w", pady=(5, 6))
        tk.Label(
            code_copy, text=self.t("Waiting for a pairing request. Codes expire after five minutes."),
            bg=CARD, fg=MUTED, font=("Segoe UI", 8), wraplength=235, justify="left",
        ).pack(anchor="w")
        qr_box = tk.Frame(code_row, bg=CARD)
        qr_box.pack(side="right", anchor="n")
        self.qr_label = tk.Label(qr_box, bg="white", bd=0)
        self.qr_label.pack()
        tk.Label(qr_box, text=self.t("SCAN & CONNECT"), bg=CARD, fg=MINT, font=("Segoe UI", 7, "bold")).pack(pady=(5, 0))
        self.qr_code = None

        controls = tk.Frame(workspace, bg=CARD, width=300, padx=18, pady=18, highlightthickness=1, highlightbackground=LINE)
        controls.pack(side="right", fill="y", padx=(9, 0))
        controls.pack_propagate(False)
        tk.Label(controls, text=self.t("Session controls"), bg=CARD, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(anchor=self.text_anchor)
        self.status = tk.Label(
            controls, text=self.t("●  NOT SHARING"), bg=GREEN, fg="white",
            font=("Segoe UI", 10, "bold"), pady=9,
        )
        self.status.pack(fill="x", pady=(12, 18))
        tk.Label(controls, text=self.t("DISPLAY TO SHARE"), bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor=self.text_anchor)
        with mss.mss() as capture:
            self.monitors = [dict(m) for m in capture.monitors[1:]]
        if not self.monitors:
            raise RuntimeError("No displays detected")
        self.select = ttk.Combobox(
            controls, state="readonly", style="PocketPC.TCombobox",
            values=[f"Display {i + 1}  ·  {m['width']} × {m['height']}" for i, m in enumerate(self.monitors)],
        )
        self.select.current(0)
        self.select.pack(fill="x", pady=(6, 14))
        self.request_text = tk.StringVar(value=self.t("Waiting for a pairing request. Codes expire after five minutes."))
        tk.Label(
            controls, textvariable=self.request_text, bg=CARD, fg=MUTED,
            font=("Segoe UI", 9), wraplength=250, justify=self.text_justify,
            anchor=self.text_anchor,
        ).pack(anchor=self.text_anchor, fill="x")
        actions = tk.Frame(controls, bg=CARD)
        actions.pack(fill="x", pady=(18, 0))
        self.approve = tk.Button(
            actions, text=self.t("APPROVE SELECTED DISPLAY"), state="disabled",
            command=lambda: self.decide(True), relief="flat", bd=0,
            bg=LINE, fg=MUTED, disabledforeground="#71828c", activebackground=MINT,
            activeforeground=MINT_DARK, font=("Segoe UI", 8, "bold"), pady=10,
        )
        self.approve.pack(fill="x")
        self.deny = tk.Button(
            actions, text=self.t("DENY"), state="disabled", command=lambda: self.decide(False),
            relief="flat", bd=0, bg=CARD_DARK, fg=MUTED, disabledforeground="#60717b",
            activebackground=LINE, activeforeground=TEXT, font=("Segoe UI", 8, "bold"), pady=9,
        )
        self.deny.pack(fill="x", pady=(7, 0))
        self.stop_button = tk.Button(
            controls, text=self.t("STOP SHARING"), command=self.stop, relief="flat", bd=0,
            bg=RED, fg="white", activebackground="#941c2b", activeforeground="white",
            font=("Segoe UI", 9, "bold"), pady=10,
        )
        self.stop_button.pack(side="bottom", fill="x")

        self._start_tray()
        self.tick()

    def _startup_command(self):
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        launcher = ROOT / "scripts" / "launch-pocketpc.pyw"
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        return f'"{pythonw}" "{launcher}"'

    def _autostart_enabled(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "PocketPC")
            return value == self._startup_command()
        except OSError:
            return False

    def _toggle_autostart(self):
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                if self.autostart.get():
                    winreg.SetValueEx(key, "PocketPC", 0, winreg.REG_SZ, self._startup_command())
                    self.request_text.set(self.t("PocketPC will start quietly when you sign in to Windows."))
                else:
                    try:
                        winreg.DeleteValue(key, "PocketPC")
                    except FileNotFoundError:
                        pass
                    self.request_text.set(self.t("Automatic startup is off. Use the desktop icon when you need PocketPC."))
        except OSError:
            self.autostart.set(self._autostart_enabled())
            self.request_text.set(self.t("Windows could not change the startup setting. Try again from your user account."))

    def show_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        window = self.settings_window = tk.Toplevel(self.root)
        window.title(f"PocketPC — {self.raw_t('Settings')}")
        window.geometry("460x560")
        window.minsize(440, 420)
        window.resizable(False, True)
        window.configure(bg=BG)
        window.transient(self.root)
        icon_file = ROOT / "assets" / "pocketpc.ico"
        if icon_file.is_file():
            window.iconbitmap(default=str(icon_file))

        def close_settings():
            self.settings_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_settings)
        viewport = tk.Frame(window, bg=BG)
        viewport.pack(fill="both", expand=True)
        canvas = tk.Canvas(viewport, bg=BG, bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = tk.Frame(canvas, bg=BG, padx=24, pady=22)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_content_width(event):
            canvas.itemconfigure(content_window, width=event.width)

        def scroll_settings(event):
            if event.delta:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", fit_content_width)
        window.bind("<MouseWheel>", scroll_settings)
        heading = tk.Frame(content, bg=BG)
        heading.pack(fill="x")
        tk.Label(heading, text=self.t("Settings"), bg=BG, fg=TEXT, font=("Segoe UI", 20, "bold")).pack(side="right" if self.language == "he" else "left")
        tk.Label(
            content, text=self.t("Choose how PocketPC behaves on this Windows PC."),
            bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor=self.text_anchor, justify=self.text_justify,
        ).pack(anchor=self.text_anchor, fill="x", pady=(5, 18))

        language_box = tk.Frame(content, bg=CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=LINE)
        language_box.pack(fill="x", pady=(0, 12))
        tk.Label(
            language_box, text=self.t("Language"), bg=CARD, fg=TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=self.text_anchor)
        language_choice = ttk.Combobox(
            language_box, state="readonly", style="PocketPC.TCombobox", values=("English", "עברית"),
        )
        language_choice.current(1 if self.language == "he" else 0)
        language_choice.pack(fill="x", pady=(7, 5))
        language_note = tk.Label(
            language_box, text=self.t("Language changes after PocketPC restarts."),
            bg=CARD, fg=MUTED, font=("Segoe UI", 8), anchor=self.text_anchor, justify=self.text_justify,
        )
        language_note.pack(fill="x")
        pending_language = {"value": self.language}

        def language_changed(_event=None):
            next_language = "he" if language_choice.current() == 1 else "en"
            pending_language["value"] = next_language
            changed = next_language != self.language
            if changed:
                message = (
                    "לחץ על ‘החל והפעל מחדש’ כדי לשנות את השפה."
                    if next_language == "he" else
                    "Click Apply & Restart to change the language."
                )
                language_note.configure(text=message)
                done_button.configure(text=self.t("APPLY & RESTART"))
            else:
                language_note.configure(text=self.t("Language changes after PocketPC restarts."))
                done_button.configure(text=self.t("DONE"))

        language_choice.bind("<<ComboboxSelected>>", language_changed)

        option = tk.Frame(content, bg=CARD, padx=16, pady=14, highlightthickness=1, highlightbackground=LINE)
        option.pack(fill="x")
        tk.Checkbutton(
            option, text=self.t("Start PocketPC with Windows"), variable=self.autostart,
            command=self._toggle_autostart, bg=CARD, fg=TEXT,
            activebackground=CARD, activeforeground=TEXT, selectcolor=CARD_DARK,
            font=("Segoe UI", 10, "bold"), bd=0, highlightthickness=0,
        ).pack(anchor=self.text_anchor)
        tk.Label(
            option, text=self.t("PocketPC starts ready, but never shares a screen until you approve."),
            bg=CARD, fg=MUTED, font=("Segoe UI", 8), wraplength=350, justify=self.text_justify,
        ).pack(anchor=self.text_anchor, padx=(0, 22) if self.language == "he" else (22, 0), pady=(5, 0))

        quality = tk.Frame(content, bg=CARD, padx=16, pady=14, highlightthickness=1, highlightbackground=LINE)
        quality.pack(fill="x", pady=(12, 0))
        tk.Label(
            quality, text=self.t("Adaptive screen quality"), bg=CARD, fg=TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=self.text_anchor)
        tk.Label(
            quality, text=self.t("Automatically balances clarity and smoothness from 720p to 1080p.\nYou can choose a fixed quality from Settings on your phone."),
            bg=CARD, fg=MUTED, font=("Segoe UI", 8), wraplength=350, justify=self.text_justify,
        ).pack(anchor=self.text_anchor, pady=(5, 0))
        tk.Label(
            quality, text=self.t("12–20 FPS  ·  encrypted WebRTC  ·  up to 8 Mbps"),
            bg=CARD_DARK, fg=MINT, font=("Segoe UI", 8, "bold"), padx=10, pady=7,
        ).pack(fill="x", pady=(10, 0))

        diagnostics = tk.Frame(content, bg=CARD, padx=16, pady=14, highlightthickness=1, highlightbackground=LINE)
        diagnostics.pack(fill="x", pady=(12, 0))
        tk.Label(
            diagnostics, text=self.t("Connection Assistant"), bg=CARD, fg=TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=self.text_anchor)
        tk.Label(
            diagnostics, text=self.t("Check the private network, video path and performance engine."),
            bg=CARD, fg=MUTED, font=("Segoe UI", 8), wraplength=350,
            justify=self.text_justify,
        ).pack(anchor=self.text_anchor, pady=(5, 8))
        diagnostic_text = tk.StringVar(value=self.t("Run a check to confirm everything is ready."))
        diagnostic_label = tk.Label(
            diagnostics, textvariable=diagnostic_text, bg=CARD_DARK, fg=MUTED,
            font=("Segoe UI", 8), padx=10, pady=9, wraplength=330,
            justify=self.text_justify, anchor=self.text_anchor,
        )
        diagnostic_label.pack(fill="x")

        diagnostic_names = {
            "tailscale": self.t("Tailscale"),
            "https": self.t("Private HTTPS"),
            "webrtc": self.t("WebRTC video"),
            "capture": self.t("Capture engine"),
            "encoder": self.t("Video encoder"),
            "security": self.t("Security"),
        }

        def show_diagnostics(result):
            if not window.winfo_exists():
                return
            lines = []
            all_ready = True
            for key in ("tailscale", "https", "webrtc", "capture", "encoder", "security"):
                item = result.get(key, {"ok": False, "detail": "Check unavailable"})
                all_ready = all_ready and item["ok"]
                lines.append(f"{'✓' if item['ok'] else '!'}  {diagnostic_names[key]} — {self.t(item['detail'])}")
            diagnostic_text.set("\n".join(lines))
            diagnostic_label.configure(fg=MINT if all_ready else "#f0c27a")
            run_diagnostics.configure(state="normal", text=self.t("Run diagnostics"))

        def diagnostics_worker():
            try:
                result = self.diagnostics_provider()
            except Exception as error:
                result = {"security": {"ok": False, "detail": f"Check failed: {type(error).__name__}"}}
            try:
                self.root.after(0, lambda: show_diagnostics(result))
            except tk.TclError:
                pass

        def run_diagnostic_check():
            diagnostic_text.set(self.t("Checking PocketPC…"))
            diagnostic_label.configure(fg=MUTED)
            run_diagnostics.configure(state="disabled", text=self.t("Checking PocketPC…"))
            threading.Thread(target=diagnostics_worker, name="PocketPC-diagnostics", daemon=True).start()

        run_diagnostics = tk.Button(
            diagnostics, text=self.t("Run diagnostics"), command=run_diagnostic_check,
            relief="flat", bd=0, bg=LINE, fg=TEXT,
            activebackground=MINT, activeforeground=MINT_DARK,
            font=("Segoe UI", 9, "bold"), pady=8,
        )
        run_diagnostics.pack(fill="x", pady=(9, 0))
        tk.Label(
            content, text=self.t("Closing the main window keeps PocketPC available in the system tray.\nUse the tray menu to reopen, stop sharing, or quit."),
            bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=385, justify=self.text_justify,
        ).pack(anchor=self.text_anchor, pady=(16, 18))
        def apply_and_close():
            next_language = pending_language["value"]
            if next_language == self.language:
                close_settings()
                return
            self._save_language(next_language)
            language_choice.configure(state="disabled")
            done_button.configure(state="disabled")
            language_note.configure(
                text=(
                    "השפה נשמרה. PocketPC מופעל מחדש…"
                    if next_language == "he" else
                    "Language saved. Restarting PocketPC…"
                )
            )
            window.after(250, self.on_restart)

        done_button = tk.Button(
            content, text=self.t("DONE"), command=apply_and_close, relief="flat", bd=0,
            bg=MINT, fg=MINT_DARK, activebackground="#83cdb7", activeforeground=MINT_DARK,
            font=("Segoe UI", 9, "bold"), pady=9,
        )
        done_button.pack(fill="x")
        window.update_idletasks()
        use_native_windows_icon(window, icon_file)
        use_dark_windows_frame(window)

    def _start_tray(self):
        icon_path = ROOT / "assets" / "pocketpc-icon.png"
        if not icon_path.is_file():
            return
        tray_image = Image.open(icon_path).convert("RGBA")
        menu = pystray.Menu(
            pystray.MenuItem(self.raw_t("Open PocketPC"), lambda _icon, _item: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem(self.raw_t("Stop sharing"), lambda _icon, _item: self.root.after(0, self.stop)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self.raw_t("Quit PocketPC"), lambda _icon, _item: self.root.after(0, self.quit)),
        )
        self.tray = pystray.Icon("PocketPC", tray_image, "PocketPC — not sharing", menu)
        self.tray.run_detached()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_to_tray(self):
        self.root.withdraw()
        if self.tray and not self.tray_hint_shown:
            self.tray_hint_shown = True
            try:
                self.tray.notify(self.raw_t("PocketPC is still ready. Open it from the tray at any time."), "PocketPC")
            except (NotImplementedError, OSError):
                pass

    def _approval_buttons(self, enabled):
        self.approve.configure(state="normal" if enabled else "disabled", bg=MINT if enabled else LINE, fg=MINT_DARK if enabled else MUTED)
        self.deny.configure(state="normal" if enabled else "disabled")

    def _set_pairing_display(self, code):
        self.code_text.set(code)
        if self.qr_code == code:
            return
        # A URL fragment is handled only by Safari; it is never included in
        # the HTTPS request, proxy logs, or Referrer header.
        qr_image = qrcode.make(f"{self.url}#pair={code}").convert("RGB").resize(
            (82, 82), Image.Resampling.NEAREST
        )
        self.qr_photo = ImageTk.PhotoImage(qr_image)
        self.qr_label.configure(image=self.qr_photo)
        self.qr_code = code

    def valid_code(self, value):
        with self.lock:
            return self.code.valid(value)

    def request_approval(self, session, peer, mouse_requested=False):
        future = Future()
        self.events.put(("request", session, peer, bool(mouse_requested), future))
        return future

    def ended(self, session, resumable_seconds=0):
        self.events.put(("ended", session, resumable_seconds))

    def input_unavailable(self, session):
        self.events.put(("input-unavailable", session))

    def resumed(self, session, display, mouse_control=False):
        self.events.put(("resumed", session, display, bool(mouse_control)))

    def decide(self, allowed):
        if not self.current or not self.approval or self.approval.done():
            return
        if self.current.cancelled.is_set():
            allowed = False
        monitor = {
            "region": dict(self.monitors[self.select.current()]),
            "topology": self.monitors,
            "display": self.select.current() + 1,
            "mouse_control": self.mouse_requested,
        } if allowed else None
        self.approval.set_result(monitor)
        self._approval_buttons(False)
        if allowed:
            self.select.configure(state="disabled")
            display = self.select.current() + 1
            sharing_text = (
                self.visual_hebrew(f"●  שליטת עכבר פעילה · מסך {display}")
                if self.language == "he" and self.mouse_requested else
                f"●  REMOTE MOUSE ACTIVE · DISPLAY {display}" if self.mouse_requested else
                self.visual_hebrew(f"●  משתף מסך {display}") if self.language == "he" else
                f"●  SHARING DISPLAY {display}"
            )
            self.status.configure(text=sharing_text, bg=RED)
            self.root.title(f"PocketPC — SHARING DISPLAY {display} — click to stop")
            if self.tray:
                self.tray.title = f"PocketPC — sharing display {display}"
            self.request_text.set(
                self.t("Mouse control is active for this approved session. Keyboard and files remain blocked.")
                if self.mouse_requested else
                self.t("Sharing is active. You may minimize this window and restore it from the taskbar to stop.")
            )
        else:
            self.stop()

    def stop(self):
        if self.current:
            self.current.cancelled.set()
        if self.approval and not self.approval.done():
            self.approval.set_result(None)
        self._approval_buttons(False)
        self.mouse_requested = False
        self.approve.configure(text=self.t("APPROVE SELECTED DISPLAY"))
        self.status.configure(text=self.t("●  STOPPED — NOT SHARING"), bg=GREEN)
        self.root.title("PocketPC")
        if self.tray:
            self.tray.title = "PocketPC — not sharing"
        self.on_stop()
        with self.lock:
            self.code.rotate()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.stop()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def tick(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "request":
                    _, session, peer, mouse_requested, future = event
                    if session.cancelled.is_set() or future.done():
                        continue
                    self.current, self.approval = session, future
                    self.mouse_requested = mouse_requested
                    self.root.title("PocketPC — APPROVAL REQUIRED")
                    if self.tray:
                        self.tray.title = "PocketPC — approval required"
                    approval_status = self.visual_hebrew("●  נדרש אישור — לא משתף") if self.language == "he" else "●  APPROVAL REQUIRED — NOT SHARING"
                    request_message = (
                        self.visual_hebrew(f"בקשה מאת {peer} לצפייה ולשליטה בעכבר. בחר מסך ואשר רק אם זה הטלפון שלך.")
                        if self.language == "he" and mouse_requested else
                        self.visual_hebrew(f"בקשה מאת {peer}. ודא שזה הטלפון שלך, בחר מסך ואשר. תוקף הבקשה 45 שניות.")
                        if self.language == "he" else
                        f"Request from {peer} for screen viewing and mouse control. Approve only if this is your phone."
                        if mouse_requested else
                        f"Request from {peer}. Confirm it is your phone, choose a display, then approve. Expires in 45 seconds."
                    )
                    self.status.configure(text=approval_status, bg=AMBER)
                    self.request_text.set(request_message)
                    self.approve.configure(
                        text=self.t("ALLOW VIEW + MOUSE") if mouse_requested
                        else self.t("APPROVE SELECTED DISPLAY")
                    )
                    self._approval_buttons(True)
                    self.root.deiconify()
                    self.root.lift()
                    self.root.attributes("-topmost", True)
                    self.root.after(1200, lambda: self.root.attributes("-topmost", False))
                    self.root.bell()
                    if self.tray:
                        try:
                            self.tray.notify(
                                "Your phone is requesting screen and mouse control."
                                if mouse_requested else "Your phone is asking to view a display.",
                                "PocketPC approval required",
                            )
                        except (NotImplementedError, OSError):
                            pass
                elif event[0] == "resumed":
                    _, session, display, mouse_control = event
                    self.current, self.approval = session, None
                    self.mouse_requested = mouse_control
                    self.select.configure(state="disabled")
                    self._approval_buttons(False)
                    sharing_text = (
                        self.visual_hebrew(f"●  שליטת עכבר פעילה · מסך {display}")
                        if self.language == "he" and mouse_control else
                        f"●  REMOTE MOUSE ACTIVE · DISPLAY {display}" if mouse_control else
                        self.visual_hebrew(f"●  משתף מסך {display}") if self.language == "he" else
                        f"●  SHARING DISPLAY {display}"
                    )
                    self.status.configure(text=sharing_text, bg=RED)
                    self.root.title(f"PocketPC — SHARING DISPLAY {display} — click to stop")
                    if self.tray:
                        self.tray.title = f"PocketPC — sharing display {display}"
                    self.request_text.set(self.t("The approved phone reconnected automatically."))
                elif event[0] == "input-unavailable" and self.current is event[1]:
                    self.mouse_requested = False
                    display = self.select.current() + 1
                    self.status.configure(
                        text=self.visual_hebrew(f"●  משתף מסך {display}") if self.language == "he" else f"●  SHARING DISPLAY {display}",
                        bg=RED,
                    )
                    self.request_text.set(self.t("Input control ended. Screen viewing remains active."))
                elif event[0] == "ended" and (self.current is event[1] or self.current is None):
                    _, _, resumable_seconds = event
                    self.current = self.approval = None
                    self.mouse_requested = False
                    self.approve.configure(text=self.t("APPROVE SELECTED DISPLAY"))
                    self.select.configure(state="readonly")
                    self._approval_buttons(False)
                    self.status.configure(text=self.t("●  NOT SHARING"), bg=GREEN)
                    self.root.title("PocketPC")
                    if self.tray:
                        self.tray.title = "PocketPC — not sharing"
                    if resumable_seconds:
                        self.request_text.set(self.t("Connection interrupted. The approved phone may reconnect automatically for up to five minutes."))
                    else:
                        self.request_text.set(self.t("Session ended. Every new connection requires your approval."))
                    with self.lock:
                        self.code.rotate()
                elif event[0] == "error":
                    self.stop()
                    self.request_text.set(event[1])
        except queue.Empty:
            pass
        with self.lock:
            if not self.code.valid(self.code.value):
                self.code.rotate()
            self._set_pairing_display(self.code.value)
        self.root.after(100, self.tick)
