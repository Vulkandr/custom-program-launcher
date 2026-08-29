import glob
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

try:
    import winreg
except ImportError:
    winreg = None

import sv_ttk
import pywinstyles

CONFIG_DIR = os.path.join(os.path.expanduser("~"), "Documents")
CONFIG_FILE = os.path.join(CONFIG_DIR, ".program_launcher_config.json")
_OLD_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".program_launcher_config.json")


def _migrate_old_config():
    """One-time migration: earlier versions stored the config directly in the user
    folder. Move it into Documents if it hasn't been migrated already."""
    if os.path.exists(CONFIG_FILE) or not os.path.exists(_OLD_CONFIG_FILE):
        return
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.replace(_OLD_CONFIG_FILE, CONFIG_FILE)
    except OSError:
        pass  # Not critical - worst case the app just starts fresh in the new location


def resource_path(relative_path):
    """Get an absolute path to a resource, whether running from source or a PyInstaller bundle."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def _load_app_version():
    try:
        with open(resource_path("version.txt"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"


APP_VERSION = _load_app_version()

# Once the GitHub repo exists, set this to its URL (e.g. "https://github.com/yourname/your-repo")
# and the "Version" item in the Settings menu will open it. Leave as None until then.
REPO_URL = "https://github.com/Vulkandr/custom-program-launcher"


def open_repo_link():
    """Open the GitHub repo if REPO_URL is set; otherwise just show the current version."""
    if REPO_URL:
        webbrowser.open(REPO_URL)
    else:
        messagebox.showinfo("Version", f"Custom Program Launcher\nVersion {APP_VERSION}")


STARTUP_APP_NAME = "CustomProgramLauncher"
STARTUP_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_startup_command():
    """Build the command line to launch this app, whether running as a script or a frozen exe.

    Appends --autostart so the app can tell a Windows-startup launch apart from someone
    manually opening it - used to gate the auto-launch-a-profile feature to startup only.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --autostart'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}" --autostart'


def _enum_visible_windows():
    """Return a set of handles for visible, top-level, titled windows."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return set()

    found = set()
    user32 = ctypes.windll.user32

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindow(hwnd, 4):  # GW_OWNER - skip owned/dialog windows
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                found.add(hwnd)
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception:
        return set()
    return found


def _apply_post_launch_action(hwnds, action):
    """Minimize or close the given windows. 'action' is 'minimize' or 'close'.

    Note on 'close': this sends the same request as clicking the window's X button.
    Apps configured to minimize to the system tray (Discord, Steam, etc.) will go to
    the tray rather than exiting - which is usually the desired outcome here. Apps
    without that behavior will simply quit.
    """
    if not hwnds or action not in ("minimize", "close"):
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
    except Exception:
        return

    SW_MINIMIZE = 6
    WM_CLOSE = 0x0010

    for hwnd in hwnds:
        try:
            if not user32.IsWindow(hwnd):
                continue
            if action == "minimize":
                user32.ShowWindow(hwnd, SW_MINIMIZE)
            else:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass


def set_startup_enabled(enabled):
    """Add or remove this app from the Windows 'Run' startup registry key."""
    if winreg is None:
        return
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY_PATH, 0, winreg.KEY_SET_VALUE)
    except OSError:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY_PATH)
    try:
        if enabled:
            winreg.SetValueEx(key, STARTUP_APP_NAME, 0, winreg.REG_SZ, _get_startup_command())
        else:
            try:
                winreg.DeleteValue(key, STARTUP_APP_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def get_windows_theme():
    """Return 'dark' or 'light' based on the current Windows personalization setting."""
    if winreg is None:
        return "light"
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "light" if value == 1 else "dark"
    except (FileNotFoundError, OSError):
        return "light"


def style_titlebar(window, theme):
    """Make the native window title bar follow the given theme ('dark' or 'light')."""
    try:
        version = sys.getwindowsversion()
        if version.major == 10 and version.build >= 22000:
            # Windows 11: color the header to match the app background
            pywinstyles.change_header_color(window, "#1c1c1c" if theme == "dark" else "#fafafa")
        elif version.major == 10:
            # Windows 10: only dark/normal title bar styles are supported
            pywinstyles.apply_style(window, "dark" if theme == "dark" else "normal")
            window.wm_attributes("-alpha", 0.99)
            window.wm_attributes("-alpha", 1)
    except Exception:
        pass  # Not on Windows, or styling unsupported - just skip it


class ProgramLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Custom Program Launcher")
        self.root.minsize(780, 440)
        self._set_initial_geometry()
        self.root.resizable(True, True)

        self.programs = []  # list of dicts: {"path": str, "delay": float, "name": str}
        self.lists = {}     # dict of list_name -> list of program dicts
        self.current_list_name = "Default"
        self.theme = get_windows_theme()
        self._settings_window = None

        # Settings (persisted alongside the program lists)
        self.settings = {
            "start_on_boot": False,
            "close_after_launch": False,
            "default_delay": 3.0,
            "autostart_list": None,  # name of the list to auto-launch on Windows startup, if any
            "remember_launch_options": True,
            "last_launch_options": {"delay_mode": "delay", "post_launch": "none"},
        }
        self.start_on_boot_var = tk.BooleanVar(value=False)
        self.close_after_launch_var = tk.BooleanVar(value=False)
        self.autostart_list_var = tk.BooleanVar(value=False)
        self.remember_launch_options_var = tk.BooleanVar(value=True)

        # State for the hover-scroll effect on long Path values
        self._marquee_item = None
        self._marquee_after_id = None
        self._marquee_original = None
        self._marquee_full = None
        self._marquee_offset = 0
        self._marquee_col_width = 0

        # State for drag-and-drop reordering
        self._item_entries = {}
        self._drag_item = None
        self._drag_moved = False

        self._build_ui()
        self._load_config()

    def _set_initial_geometry(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # Scale to a comfortable fraction of the screen, clamped between the minsize and a sane cap
        width = max(780, min(820, int(screen_w * 0.45)))
        height = max(420, min(560, int(screen_h * 0.55)))
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_settings_menu(self):
        if self.theme == "dark":
            menu_colors = {
                "bg": "#1c1c1c", "fg": "#ffffff",
                "activebackground": "#2f6fed", "activeforeground": "#ffffff",
                "disabledforeground": "#777777",
            }
        else:
            menu_colors = {
                "bg": "#fafafa", "fg": "#000000",
                "activebackground": "#2f6fed", "activeforeground": "#ffffff",
                "disabledforeground": "#aaaaaa",
            }

        settings_menu = tk.Menu(self.root, tearoff=0, **menu_colors)

        settings_menu.add_checkbutton(
            label="Open on Startup",
            variable=self.start_on_boot_var,
            command=self.toggle_start_on_boot,
        )
        settings_menu.add_checkbutton(
            label="Close After Launch All",
            variable=self.close_after_launch_var,
            command=self.toggle_close_after_launch,
        )
        settings_menu.add_separator()
        settings_menu.add_command(label="More Settings...", command=self.open_settings_window)
        settings_menu.add_separator()
        settings_menu.add_command(label=f"Version {APP_VERSION}", command=open_repo_link)

        self.settings_menu = settings_menu
        return settings_menu

    def toggle_start_on_boot(self):
        enabled = self.start_on_boot_var.get()
        self.settings["start_on_boot"] = enabled
        set_startup_enabled(enabled)
        self._save_config()
        self.status_var.set(
            "Launcher will now start with Windows." if enabled else "Removed launcher from Windows startup."
        )

    def toggle_close_after_launch(self):
        self.settings["close_after_launch"] = self.close_after_launch_var.get()
        self._save_config()

    def toggle_remember_launch_options(self):
        self.settings["remember_launch_options"] = self.remember_launch_options_var.get()
        self._save_config()

    def open_settings_window(self):
        """Full settings window. The toggles here share the same variables as the
        Settings dropdown, so changing one place updates the other automatically."""
        if getattr(self, "_settings_window", None) is not None:
            try:
                self._settings_window.lift()
                self._settings_window.focus_force()
                return
            except tk.TclError:
                self._settings_window = None

        win = tk.Toplevel(self.root)
        self._settings_window = win
        win.title("Settings")
        win.resizable(False, False)
        win.transient(self.root)
        style_titlebar(win, self.theme)

        frame = ttk.Frame(win, padding=20)
        frame.pack(fill="both", expand=True)

        # --- Startup ---
        ttk.Label(frame, text="Startup", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Checkbutton(
            frame, text="Open Custom Program Launcher when Windows starts",
            variable=self.start_on_boot_var, command=self.toggle_start_on_boot,
        ).pack(anchor="w", pady=(6, 0))

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=14)

        # --- Launching ---
        ttk.Label(frame, text="Launching", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Checkbutton(
            frame, text="Close this app after Launch All finishes",
            variable=self.close_after_launch_var, command=self.toggle_close_after_launch,
        ).pack(anchor="w", pady=(6, 0))

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=14)

        # --- Adding programs ---
        ttk.Label(frame, text="Adding Programs", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        delay_row = ttk.Frame(frame)
        delay_row.pack(fill="x", pady=(8, 0))
        ttk.Label(delay_row, text="Default delay:").pack(side="left")
        default_delay_var = tk.StringVar(value=f"{self.settings.get('default_delay', 3.0):.1f}")
        delay_entry = ttk.Entry(delay_row, textvariable=default_delay_var, width=8)
        delay_entry.pack(side="left", padx=(8, 4))
        ttk.Label(delay_row, text="seconds").pack(side="left")

        ttk.Label(
            frame, text="Pre-filled in Launch Options when adding a new program.",
            font=("Segoe UI", 9), foreground="gray",
        ).pack(anchor="w", pady=(2, 10))

        ttk.Checkbutton(
            frame, text="Remember my last Launch Options choices for the next program",
            variable=self.remember_launch_options_var, command=self.toggle_remember_launch_options,
        ).pack(anchor="w")
        ttk.Label(
            frame, text="Carries over the delay mode and start behavior (not arguments).",
            font=("Segoe UI", 9), foreground="gray",
        ).pack(anchor="w", padx=(24, 0), pady=(2, 0))

        # --- Buttons ---
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(20, 0))

        def save_and_close():
            try:
                value = float(default_delay_var.get())
                if value < 0:
                    raise ValueError
                self.settings["default_delay"] = value
            except ValueError:
                messagebox.showerror("Invalid delay", "Default delay must be a number of seconds (0 or higher).",
                                     parent=win)
                return
            self._save_config()
            on_close()

        def on_close():
            self._settings_window = None
            win.destroy()

        ttk.Button(btn_row, text="Save", style="Accent.TButton", command=save_and_close).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text="Cancel", command=on_close).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", on_close)

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- UI ----------
    def _build_ui(self):
        container = ttk.Frame(self.root, padding=0)
        container.pack(fill="both", expand=True)

        settings_menu = self._build_settings_menu()

        top_row = ttk.Frame(container)
        top_row.pack(fill="x", padx=10, pady=(10, 4))
        # Equal-width side columns keep the List picker genuinely centered in the window
        top_row.columnconfigure(0, weight=1, uniform="side")
        top_row.columnconfigure(2, weight=1, uniform="side")

        ttk.Checkbutton(
            top_row, text="Auto-launch on startup",
            variable=self.autostart_list_var, command=self.toggle_autostart_list,
        ).grid(row=0, column=0, sticky="w")

        list_frame = ttk.Frame(top_row)
        list_frame.grid(row=0, column=1)

        ttk.Label(list_frame, text="List:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.list_var = tk.StringVar()
        self.list_combo = ttk.Combobox(list_frame, textvariable=self.list_var, state="readonly", width=25)
        self.list_combo.pack(side="left", padx=(5, 0))
        self.list_combo.bind("<<ComboboxSelected>>", self.on_list_selected)

        settings_btn = ttk.Menubutton(top_row, text="Settings", menu=settings_menu)
        settings_btn.grid(row=0, column=2, sticky="e")

        list_btn_frame = ttk.Frame(container)
        list_btn_frame.pack(pady=(0, 6))

        ttk.Button(list_btn_frame, text="New List", command=self.new_list).pack(side="left", padx=2)
        ttk.Button(list_btn_frame, text="Duplicate As...", command=self.save_list_as).pack(side="left", padx=2)
        ttk.Button(list_btn_frame, text="Rename", command=self.rename_list).pack(side="left", padx=2)
        ttk.Button(list_btn_frame, text="Delete List", command=self.delete_list).pack(side="left", padx=2)

        top_frame = ttk.Frame(container)
        top_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("name", "path", "delay", "start")
        self.tree = ttk.Treeview(top_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Program")
        self.tree.heading("path", text="Path")
        self.tree.heading("delay", text="Delay")
        self.tree.heading("start", text="Start")
        self.tree.column("name", width=145, minwidth=145, stretch=False)
        self.tree.column("path", width=260, stretch=True)
        self.tree.column("delay", width=70, minwidth=70, anchor="center", stretch=False)
        self.tree.column("start", width=75, minwidth=75, anchor="center", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)
        self.tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.tree.bind("<Button-3>", self._on_right_click)

        btn_frame_row1 = ttk.Frame(container)
        btn_frame_row1.pack(pady=(0, 4))
        ttk.Button(btn_frame_row1, text="Choose Program", command=self.add_from_installed).pack(side="left", padx=5)
        ttk.Button(btn_frame_row1, text="Browse for File...", command=self.add_program).pack(side="left", padx=5)
        ttk.Button(btn_frame_row1, text="Add Script...", command=self.add_script).pack(side="left", padx=5)

        btn_frame_row2 = ttk.Frame(container)
        btn_frame_row2.pack(pady=(0, 10))
        ttk.Button(btn_frame_row2, text="Move Up", command=self.move_up).pack(side="left", padx=5)
        ttk.Button(btn_frame_row2, text="Move Down", command=self.move_down).pack(side="left", padx=5)
        ttk.Button(btn_frame_row2, text="Remove", command=self.remove_program).pack(side="left", padx=5)
        ttk.Button(btn_frame_row2, text="Launch Options", command=self.edit_launch_options).pack(side="left", padx=5)

        launch_frame = ttk.Frame(container)
        launch_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.launch_btn = ttk.Button(
            launch_frame, text="Launch All", style="Accent.TButton", command=self.launch_all
        )
        self.launch_btn.pack(side="left", fill="x", expand=True, ipady=6)

        self.status_var = tk.StringVar(value="Ready.")
        status_label = ttk.Label(container, textvariable=self.status_var, anchor="w", relief="sunken")
        status_label.pack(fill="x", side="bottom")

    # ---------- Config persistence ----------
    def _load_config(self):
        _migrate_old_config()

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "lists" in data:
                    self.lists = data.get("lists", {})
                    self.current_list_name = data.get("last_list", "Default")
                    self.settings = {
                        "start_on_boot": False,
                        "close_after_launch": False,
                        "default_delay": 3.0,
                        "autostart_list": None,
                        "remember_launch_options": True,
                        "last_launch_options": {"delay_mode": "delay", "post_launch": "none"},
                        **data.get("settings", {}),
                    }
                elif isinstance(data, list):
                    # Old format (plain list) from a previous version - migrate it in
                    self.lists = {"Default": data}
                    self.current_list_name = "Default"
            except (json.JSONDecodeError, OSError):
                self.lists = {}

        if not self.lists:
            self.lists = {"Default": []}
        if self.current_list_name not in self.lists:
            self.current_list_name = next(iter(self.lists))

        self.programs = self.lists[self.current_list_name]
        self._refresh_list_combo()
        self._refresh_tree()

        # Sync the menu checkboxes and the actual startup registry entry to the saved setting
        self.start_on_boot_var.set(self.settings.get("start_on_boot", False))
        self.close_after_launch_var.set(self.settings.get("close_after_launch", False))
        self.remember_launch_options_var.set(self.settings.get("remember_launch_options", True))
        self._refresh_autostart_checkbox()
        set_startup_enabled(self.settings.get("start_on_boot", False))

    def _save_config(self):
        self.lists[self.current_list_name] = self.programs
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"last_list": self.current_list_name, "lists": self.lists, "settings": self.settings},
                    f, indent=2,
                )
        except OSError as e:
            messagebox.showerror("Error", f"Could not save config:\n{e}")

    def _refresh_list_combo(self):
        names = sorted(self.lists.keys(), key=str.lower)
        self.list_combo["values"] = names
        self.list_var.set(self.current_list_name)

    @staticmethod
    def _get_delay_mode(entry):
        """Read an entry's delay mode, migrating older entries that used the
        separate 'wait_for_window' flag and a bare delay number."""
        mode = entry.get("delay_mode")
        if mode in ("none", "delay", "wait", "wait_delay"):
            return mode
        waits = entry.get("wait_for_window", False)
        has_delay = float(entry.get("delay", 0) or 0) > 0
        if waits and has_delay:
            return "wait_delay"
        if waits:
            return "wait"
        return "delay" if has_delay else "none"

    @staticmethod
    def _display_path(entry):
        if entry.get("type") == "script":
            shell = "PowerShell" if entry.get("shell") == "powershell" else "CMD"
            body = " ".join((entry.get("script", "") or "").split())
            return f"[{shell} script]  {body}"
        args = entry.get("args", "")
        return f"{entry['path']}  [args: {args}]" if args else entry["path"]

    def _display_delay(self, entry):
        mode = self._get_delay_mode(entry)
        delay = entry.get("delay", 0)
        if mode == "none":
            return "none"
        if mode == "delay":
            return f"{delay}s"
        if mode == "wait":
            return "wait"
        return f"w+{delay}s"

    @staticmethod
    def _display_start(entry):
        action = entry.get("post_launch", "none")
        return {"minimize": "minimize", "close": "close"}.get(action, "normal")

    def _refresh_tree(self):
        self._stop_marquee()
        self.tree.delete(*self.tree.get_children())
        self._item_entries = {}  # tree row id -> program dict, used by drag reordering
        for entry in self.programs:
            iid = self.tree.insert("", "end", values=(
                entry["name"],
                self._display_path(entry),
                self._display_delay(entry),
                self._display_start(entry),
            ))
            self._item_entries[iid] = entry

    # ---------- Drag and drop reordering ----------
    def _on_drag_start(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            self._drag_item = None
            return
        self._drag_item = self.tree.identify_row(event.y)
        self._drag_moved = False

    def _on_drag_motion(self, event):
        item = getattr(self, "_drag_item", None)
        if not item:
            return
        self._stop_marquee()
        self._drag_moved = True

        target = self.tree.identify_row(event.y)
        if target and target != item:
            # Dropping onto a row puts the dragged item above it
            self.tree.move(item, "", self.tree.index(target))
        elif not target:
            # Below the last row - send it to the bottom
            self.tree.move(item, "", "end")

    def _on_drag_release(self, _event):
        item = getattr(self, "_drag_item", None)
        moved = getattr(self, "_drag_moved", False)
        self._drag_item = None
        self._drag_moved = False
        if not item or not moved:
            return

        # Rebuild the program list to match the tree's new order. Assigning into the
        # slice mutates the list in place, which matters because self.programs is the
        # same object stored in self.lists.
        dragged_entry = self._item_entries.get(item)
        new_order = [self._item_entries[iid] for iid in self.tree.get_children()
                     if iid in self._item_entries]
        if len(new_order) != len(self.programs):
            return

        self.programs[:] = new_order
        self._refresh_tree()
        self._save_config()

        # Keep the row the user just dragged selected
        if dragged_entry is not None:
            for iid, entry in self._item_entries.items():
                if entry is dragged_entry:
                    self.tree.selection_set(iid)
                    break

    # ---------- Right-click context menu ----------
    def _on_right_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return

        self._stop_marquee()
        self.tree.selection_set(item)
        idx = self.tree.index(item)
        entry = self.programs[idx]
        is_script = entry.get("type") == "script"

        if self.theme == "dark":
            menu_colors = {
                "bg": "#1c1c1c", "fg": "#ffffff",
                "activebackground": "#2f6fed", "activeforeground": "#ffffff",
                "disabledforeground": "#777777",
            }
        else:
            menu_colors = {
                "bg": "#fafafa", "fg": "#000000",
                "activebackground": "#2f6fed", "activeforeground": "#ffffff",
                "disabledforeground": "#aaaaaa",
            }

        menu = tk.Menu(self.root, tearoff=0, **menu_colors)
        menu.add_command(label="Launch Now", command=lambda: self.launch_single(idx))
        menu.add_separator()
        menu.add_command(label="Launch Options...", command=self.edit_launch_options)
        menu.add_command(label="Rename...", command=lambda: self.rename_entry(idx))
        menu.add_command(label="Duplicate", command=lambda: self.duplicate_entry(idx))
        menu.add_command(
            label="Open File Location", command=lambda: self.open_file_location(idx),
            state="disabled" if is_script else "normal",
        )
        menu.add_separator()
        menu.add_command(label="Remove", command=self.remove_program)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def launch_single(self, idx):
        """Launch just one entry, handy for testing a script or a single program."""
        if idx >= len(self.programs):
            return
        entry = self.programs[idx]
        self._set_status(f"Launching '{entry['name']}'...")

        def run():
            try:
                self._launch_entry(entry)
                self._set_status(f"Launched '{entry['name']}'.")
            except Exception as e:
                self._set_status(f"Failed to launch '{entry['name']}': {e}")

        threading.Thread(target=run, daemon=True).start()

    def rename_entry(self, idx):
        if idx >= len(self.programs):
            return
        entry = self.programs[idx]
        new_name = simpledialog.askstring("Rename", "Name for this entry:", initialvalue=entry["name"])
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        entry["name"] = new_name
        self._refresh_tree()
        self._save_config()

    def duplicate_entry(self, idx):
        if idx >= len(self.programs):
            return
        copy = dict(self.programs[idx])
        copy["name"] = f"{copy['name']} (copy)"
        self.programs.insert(idx + 1, copy)
        self._refresh_tree()
        self._save_config()

    def open_file_location(self, idx):
        if idx >= len(self.programs):
            return
        entry = self.programs[idx]
        path = entry.get("path", "")
        if not path:
            return
        if not os.path.exists(path):
            messagebox.showinfo("Not found", f"Couldn't find:\n{path}")
            return
        try:
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"', shell=True)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open the folder:\n{e}")

    def _get_tree_font(self):
        style = ttk.Style()
        font_spec = style.lookup("Treeview", "font") or "TkDefaultFont"
        try:
            return tkfont.nametofont(font_spec)
        except tk.TclError:
            return tkfont.Font(font=font_spec)

    # ---------- Path hover-scroll effect ----------
    def _on_tree_motion(self, event):
        if getattr(self, "_drag_item", None):
            return  # don't start the hover-scroll mid-drag
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            self._stop_marquee()
            return

        col = self.tree.identify_column(event.x)   # "#2" is the Path column (name, path, delay)
        item = self.tree.identify_row(event.y)

        if col != "#2" or not item:
            self._stop_marquee()
            return

        if item == self._marquee_item:
            return  # already hovering/animating this exact cell

        self._stop_marquee()

        idx = self.tree.index(item)
        if idx >= len(self.programs):
            return

        full_path = self._display_path(self.programs[idx])
        col_width = self.tree.column("path", "width")

        self._marquee_item = item
        self._marquee_original = full_path
        self._marquee_full = full_path + "      "  # trailing spacer so the tail isn't clipped by cell padding
        self._marquee_offset = 0
        self._marquee_col_width = col_width
        self._animate_marquee()

    def _animate_marquee(self):
        if self._marquee_item is None:
            return
        f = self._get_tree_font()
        remaining = self._marquee_full[self._marquee_offset:]

        try:
            self.tree.set(self._marquee_item, "path", remaining)
        except tk.TclError:
            self._stop_marquee()
            return

        if f.measure(remaining) <= self._marquee_col_width - 4 or self._marquee_offset >= len(self._marquee_full) - 1:
            self._marquee_after_id = None  # reached the tail - hold here until mouse leaves
            return

        self._marquee_offset += 1
        self._marquee_after_id = self.root.after(35, self._animate_marquee)

    def _stop_marquee(self):
        if self._marquee_after_id is not None:
            try:
                self.root.after_cancel(self._marquee_after_id)
            except Exception:
                pass
            self._marquee_after_id = None
        if self._marquee_item is not None and self._marquee_original is not None:
            try:
                self.tree.set(self._marquee_item, "path", self._marquee_original)
            except tk.TclError:
                pass
        self._marquee_item = None
        self._marquee_original = None
        self._marquee_full = None
        self._marquee_offset = 0

    def _on_tree_leave(self, _event=None):
        self._stop_marquee()

    # ---------- List management ----------
    def on_list_selected(self, _event=None):
        selected = self.list_var.get()
        if selected == self.current_list_name:
            return
        self.current_list_name = selected
        self.programs = self.lists[self.current_list_name]
        self._refresh_tree()
        self._refresh_autostart_checkbox()
        self._save_config()
        self.status_var.set(f"Switched to list '{self.current_list_name}'.")

    def _refresh_autostart_checkbox(self):
        self.autostart_list_var.set(self.settings.get("autostart_list") == self.current_list_name)

    def toggle_autostart_list(self):
        if self.autostart_list_var.get():
            self.settings["autostart_list"] = self.current_list_name
        elif self.settings.get("autostart_list") == self.current_list_name:
            self.settings["autostart_list"] = None
        self._save_config()

    def new_list(self):
        name = simpledialog.askstring("New List", "Name for the new list:")
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self.lists:
            messagebox.showerror("Error", f"A list named '{name}' already exists.")
            return
        self.lists[name] = []
        self.current_list_name = name
        self.programs = self.lists[name]
        self._refresh_list_combo()
        self._refresh_tree()
        self._refresh_autostart_checkbox()
        self._save_config()

    def save_list_as(self):
        name = simpledialog.askstring("Duplicate As", "Duplicate current list as:", initialvalue=self.current_list_name)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self.lists and name != self.current_list_name:
            if not messagebox.askyesno("Overwrite?", f"A list named '{name}' already exists. Overwrite it?"):
                return
        # Copy the current programs into the new/target list name
        self.lists[name] = [dict(p) for p in self.programs]
        self.current_list_name = name
        self.programs = self.lists[name]
        self._refresh_list_combo()
        self._refresh_tree()
        self._refresh_autostart_checkbox()
        self._save_config()

    def rename_list(self):
        new_name = simpledialog.askstring("Rename List", "New name:", initialvalue=self.current_list_name)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or new_name == self.current_list_name:
            return
        if new_name in self.lists:
            messagebox.showerror("Error", f"A list named '{new_name}' already exists.")
            return
        self.lists[new_name] = self.lists.pop(self.current_list_name)
        if self.settings.get("autostart_list") == self.current_list_name:
            self.settings["autostart_list"] = new_name
        self.current_list_name = new_name
        self._refresh_list_combo()
        self._refresh_autostart_checkbox()
        self._save_config()

    def delete_list(self):
        if len(self.lists) <= 1:
            messagebox.showinfo("Can't delete", "You need at least one list.")
            return
        if not messagebox.askyesno("Delete List", f"Delete the list '{self.current_list_name}'? This can't be undone."):
            return
        del self.lists[self.current_list_name]
        if self.settings.get("autostart_list") == self.current_list_name:
            self.settings["autostart_list"] = None
        self.current_list_name = next(iter(self.lists))
        self.programs = self.lists[self.current_list_name]
        self._refresh_list_combo()
        self._refresh_tree()
        self._refresh_autostart_checkbox()
        self._save_config()

    # ---------- Installed program scanning ----------
    @staticmethod
    def _scan_start_menu_shortcuts():
        """Scan Start Menu folders for .lnk shortcuts, return sorted list of (name, path)."""
        search_dirs = [
            os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.environ.get("ProgramData", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
        ]
        found = {}
        for base_dir in search_dirs:
            if not base_dir or not os.path.isdir(base_dir):
                continue
            pattern = os.path.join(base_dir, "**", "*.lnk")
            for shortcut_path in glob.glob(pattern, recursive=True):
                name = os.path.splitext(os.path.basename(shortcut_path))[0]
                # Skip common noise entries
                if name.lower() in ("uninstall", "readme", "help", "website", "documentation"):
                    continue
                if name not in found:
                    found[name] = shortcut_path
        return sorted(found.items(), key=lambda x: x[0].lower())

    def add_from_installed(self):
        shortcuts = self._scan_start_menu_shortcuts()
        if not shortcuts:
            messagebox.showinfo(
                "No shortcuts found",
                "Couldn't find any Start Menu shortcuts. Use 'Browse for File...' instead."
            )
            return

        picker = tk.Toplevel(self.root)
        picker.title("Choose Program")
        picker.geometry("400x450")
        picker.transient(self.root)
        picker.grab_set()
        style_titlebar(picker, self.theme)

        ttk.Label(picker, text="Search:").pack(anchor="w", padx=10, pady=(10, 0))
        search_var = tk.StringVar()
        search_entry = ttk.Entry(picker, textvariable=search_var)
        search_entry.pack(fill="x", padx=10)
        search_entry.focus_set()

        list_frame = ttk.Frame(picker)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)

        if self.theme == "dark":
            listbox_colors = {"bg": "#1c1c1c", "fg": "#ffffff", "selectbackground": "#2f6fed", "selectforeground": "#ffffff"}
        else:
            listbox_colors = {"bg": "#fafafa", "fg": "#000000", "selectbackground": "#2f6fed", "selectforeground": "#ffffff"}

        listbox = tk.Listbox(list_frame, borderwidth=0, highlightthickness=0, **listbox_colors)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        scrollbar.pack(side="right", fill="y")
        listbox.configure(yscrollcommand=scrollbar.set)

        def populate(filter_text=""):
            listbox.delete(0, tk.END)
            filter_text = filter_text.lower()
            for name, _ in shortcuts:
                if filter_text in name.lower():
                    listbox.insert(tk.END, name)

        populate()

        def on_search_change(*_args):
            populate(search_var.get())

        search_var.trace_add("write", on_search_change)

        name_to_path = dict(shortcuts)

        def confirm_selection(_event=None):
            sel = listbox.curselection()
            if not sel:
                return
            chosen_name = listbox.get(sel[0])
            chosen_path = name_to_path[chosen_name]
            picker.destroy()
            self.root.after(150, lambda: self._prompt_delay_and_add(chosen_name, chosen_path))

        listbox.bind("<Double-Button-1>", confirm_selection)
        search_entry.bind("<Return>", confirm_selection)

        btn_row = ttk.Frame(picker)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="Select", command=confirm_selection).pack(side="left", expand=True, fill="x")
        ttk.Button(btn_row, text="Cancel", command=picker.destroy).pack(side="left", expand=True, fill="x")

    def _prompt_delay_and_add(self, name, path):
        """Open Launch Options for a newly added program, pre-filled with either the
        remembered choices from last time or the defaults."""
        remembered = {}
        if self.settings.get("remember_launch_options", True):
            remembered = self.settings.get("last_launch_options", {}) or {}

        initial = {
            "args": "",
            "delay": remembered.get("delay", self.settings.get("default_delay", 3.0)),
            "delay_mode": remembered.get("delay_mode", "delay"),
            "post_launch": remembered.get("post_launch", "none"),
        }

        def on_save(result):
            self.programs.append({"name": name, "path": path, **result})
            self._refresh_tree()
            self._save_config()

        self._show_launch_options_dialog(name, initial, on_save)

    # ---------- Program list management ----------
    def add_program(self):
        path = filedialog.askopenfilename(
            title="Select a program",
            filetypes=[
                ("Programs & Scripts", "*.exe;*.lnk;*.bat;*.cmd;*.ps1;*.vbs"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        name = os.path.splitext(os.path.basename(path))[0]
        self.root.after(150, lambda: self._prompt_delay_and_add(name, path))

    def add_script(self):
        """Create an entry that runs an inline PowerShell or CMD script."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Script")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        style_titlebar(dialog, self.theme)

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Name:").pack(anchor="w")
        name_var = tk.StringVar()
        name_entry = ttk.Entry(frame, textvariable=name_var, width=52)
        name_entry.pack(fill="x", pady=(4, 14))

        ttk.Label(frame, text="Run with:").pack(anchor="w")
        shell_var = tk.StringVar(value="powershell")
        shell_row = ttk.Frame(frame)
        shell_row.pack(anchor="w", pady=(4, 14))
        ttk.Radiobutton(shell_row, text="PowerShell", variable=shell_var, value="powershell").pack(side="left")
        ttk.Radiobutton(shell_row, text="Command Prompt", variable=shell_var,
                        value="cmd").pack(side="left", padx=(14, 0))

        ttk.Label(frame, text="Script:").pack(anchor="w")
        text_colors = (
            {"bg": "#1c1c1c", "fg": "#ffffff", "insertbackground": "#ffffff"}
            if self.theme == "dark" else
            {"bg": "#ffffff", "fg": "#000000", "insertbackground": "#000000"}
        )
        script_text = tk.Text(frame, width=64, height=9, wrap="none",
                              borderwidth=1, relief="solid", **text_colors)
        script_text.pack(fill="both", expand=True, pady=(4, 4))

        ttk.Label(
            frame,
            text='Example:  & "$env:LOCALAPPDATA\\Discord\\Update.exe" --processStart Discord.exe',
            font=("Consolas", 9), foreground="gray",
        ).pack(anchor="w", pady=(0, 16))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x")

        def next_step():
            name = name_var.get().strip()
            body = script_text.get("1.0", "end").strip()
            if not name:
                messagebox.showerror("Name required", "Give this script a name.", parent=dialog)
                return
            if not body:
                messagebox.showerror("Script required", "Enter the script to run.", parent=dialog)
                return
            shell = shell_var.get()
            dialog.destroy()
            self.root.after(150, lambda: self._prompt_delay_and_add_script(name, shell, body))

        ttk.Button(btn_row, text="Next", style="Accent.TButton", command=next_step).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right")

        dialog.update_idletasks()
        w, h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dialog.geometry(f"{w}x{h}+{x}+{y}")

        dialog.grab_set()
        name_entry.focus_set()

    def _prompt_delay_and_add_script(self, name, shell, body):
        remembered = {}
        if self.settings.get("remember_launch_options", True):
            remembered = self.settings.get("last_launch_options", {}) or {}

        remembered_mode = remembered.get("delay_mode", "delay")
        if remembered_mode in ("wait", "wait_delay"):
            remembered_mode = "delay"  # wait modes don't apply to scripts

        initial = {
            "args": "",
            "script": body,
            "shell": shell,
            "type": "script",
            "delay": remembered.get("delay", self.settings.get("default_delay", 3.0)),
            "delay_mode": remembered_mode,
            "post_launch": "none",
        }

        def on_save(result):
            self.programs.append({
                "name": name, "path": "", "type": "script", "shell": shell, **result,
            })
            self._refresh_tree()
            self._save_config()

        self._show_launch_options_dialog(name, initial, on_save, is_script=True)

    def _get_selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.index(sel[0])

    def remove_program(self):
        idx = self._get_selected_index()
        if idx is None:
            messagebox.showinfo("No selection", "Select a program to remove first.")
            return
        del self.programs[idx]
        self._refresh_tree()
        self._save_config()

    def move_up(self):
        idx = self._get_selected_index()
        if idx is None or idx == 0:
            return
        self.programs[idx - 1], self.programs[idx] = self.programs[idx], self.programs[idx - 1]
        self._refresh_tree()
        self._save_config()
        self.tree.selection_set(self.tree.get_children()[idx - 1])

    def move_down(self):
        idx = self._get_selected_index()
        if idx is None or idx >= len(self.programs) - 1:
            return
        self.programs[idx + 1], self.programs[idx] = self.programs[idx], self.programs[idx + 1]
        self._refresh_tree()
        self._save_config()
        self.tree.selection_set(self.tree.get_children()[idx + 1])

    def edit_launch_options(self):
        idx = self._get_selected_index()
        if idx is None:
            messagebox.showinfo("No selection", "Select a program to edit first.")
            return
        entry = self.programs[idx]
        is_script = entry.get("type") == "script"

        initial = {
            "args": entry.get("args", ""),
            "script": entry.get("script", ""),
            "shell": entry.get("shell", "powershell"),
            "delay": entry.get("delay", self.settings.get("default_delay", 3.0)),
            "delay_mode": self._get_delay_mode(entry),
            "post_launch": entry.get("post_launch", "none"),
        }

        def on_save(result):
            entry.update(result)
            entry.pop("wait_for_window", None)  # superseded by delay_mode
            self._refresh_tree()
            self._save_config()

        self._show_launch_options_dialog(entry["name"], initial, on_save, is_script=is_script)

    def _show_launch_options_dialog(self, program_name, initial, on_save, is_script=False):
        """Shared Launch Options dialog, used both when adding a new program and
        when editing an existing one. Calls on_save(result_dict) if saved.

        For script entries the arguments field is replaced with an editable script box
        (arguments don't apply to an inline script), and the start behavior is locked
        to Normally, since a script has no window of its own to minimize or close.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("Launch Options")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        style_titlebar(dialog, self.theme)

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=program_name, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 14))

        args_var = tk.StringVar(value=initial.get("args", ""))
        script_widget = None
        args_entry = None

        if is_script:
            # --- Script body (replaces arguments, which don't apply here) ---
            shell_name = "PowerShell" if initial.get("shell") == "powershell" else "Command Prompt"
            ttk.Label(frame, text=f"Script ({shell_name}):").pack(anchor="w")
            text_colors = (
                {"bg": "#1c1c1c", "fg": "#ffffff", "insertbackground": "#ffffff"}
                if self.theme == "dark" else
                {"bg": "#ffffff", "fg": "#000000", "insertbackground": "#000000"}
            )
            script_widget = tk.Text(frame, width=64, height=8, wrap="none",
                                    borderwidth=1, relief="solid", **text_colors)
            script_widget.insert("1.0", initial.get("script", ""))
            script_widget.pack(fill="both", expand=True, pady=(4, 16))
        else:
            # --- Arguments ---
            ttk.Label(frame, text="Command-line arguments (optional):").pack(anchor="w")
            args_entry = ttk.Entry(frame, textvariable=args_var, width=52)
            args_entry.pack(fill="x", pady=(4, 16))

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(0, 14))

        # --- Delay / wait ---
        ttk.Label(frame, text="Before moving to the next program:",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")

        delay_row = ttk.Frame(frame)
        delay_row.pack(anchor="w", pady=(8, 8))
        ttk.Label(delay_row, text="Delay:").pack(side="left")
        delay_var = tk.StringVar(value=f"{float(initial.get('delay', 3.0)):.1f}")
        delay_entry = ttk.Entry(delay_row, textvariable=delay_var, width=8)
        delay_entry.pack(side="left", padx=(8, 4))
        seconds_label = ttk.Label(delay_row, text="seconds")
        seconds_label.pack(side="left")

        initial_mode = initial.get("delay_mode", "delay")
        if is_script and initial_mode in ("wait", "wait_delay"):
            # Wait modes don't apply to scripts (see note below) - fall back to delay
            initial_mode = "delay" if initial.get("delay", 0) else "none"
        mode_var = tk.StringVar(value=initial_mode)

        def sync_delay_field(*_args):
            uses_delay = mode_var.get() in ("delay", "wait_delay")
            delay_entry.configure(state="normal" if uses_delay else "disabled")
            seconds_label.configure(foreground="" if uses_delay else "gray")

        wait_state = "disabled" if is_script else "normal"
        ttk.Radiobutton(frame, text="No delay: continue immediately",
                        variable=mode_var, value="none", command=sync_delay_field).pack(anchor="w")
        ttk.Radiobutton(frame, text="Delay: wait the number of seconds above",
                        variable=mode_var, value="delay", command=sync_delay_field).pack(anchor="w")
        ttk.Radiobutton(frame, text="Wait: wait until this program's window appears",
                        variable=mode_var, value="wait", command=sync_delay_field,
                        state=wait_state).pack(anchor="w")
        ttk.Radiobutton(frame, text="Wait & delay: wait for the window, then the delay above",
                        variable=mode_var, value="wait_delay", command=sync_delay_field,
                        state=wait_state).pack(anchor="w")

        if is_script:
            note = ("Waiting doesn't apply to scripts: there's no window to wait for,\n"
                    "so it would just sit until it gave up.")
        else:
            note = ("Waiting gives up after 60 seconds, and won't work for programs\n"
                    "that start hidden or only in the system tray.")
        ttk.Label(
            frame, text=note,
            font=("Segoe UI", 9), foreground="gray", justify="left",
        ).pack(anchor="w", padx=(24, 0), pady=(4, 0))

        sync_delay_field()

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=14)

        # --- Post-launch action ---
        label_text = "Start this script:" if is_script else "Start this program:"
        ttk.Label(frame, text=label_text, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        action_var = tk.StringVar(value="none" if is_script else initial.get("post_launch", "none"))
        radio_state = "disabled" if is_script else "normal"
        ttk.Radiobutton(frame, text="Normally", variable=action_var,
                        value="none").pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(frame, text="Then minimize it to the taskbar", variable=action_var,
                        value="minimize", state=radio_state).pack(anchor="w")
        ttk.Radiobutton(frame, text="Then close its window (goes to the system tray for apps that support it)",
                        variable=action_var, value="close", state=radio_state).pack(anchor="w")
        if is_script:
            ttk.Label(
                frame, text="Scripts have no window of their own to minimize or close.",
                font=("Segoe UI", 9), foreground="gray",
            ).pack(anchor="w", padx=(24, 0), pady=(4, 0))

        # --- Buttons ---
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(20, 0))

        def save_and_close():
            mode = mode_var.get()
            delay_value = 0.0
            if mode in ("delay", "wait_delay"):
                try:
                    delay_value = float(delay_var.get())
                    if delay_value < 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("Invalid delay",
                                         "Delay must be a number of seconds (0 or higher).", parent=dialog)
                    return

            result = {
                "delay": delay_value,
                "delay_mode": mode,
                "post_launch": action_var.get(),
            }

            if is_script:
                body = script_widget.get("1.0", "end").strip()
                if not body:
                    messagebox.showerror("Script required", "Enter the script to run.", parent=dialog)
                    return
                result["script"] = body
                result["args"] = ""
            else:
                result["args"] = args_var.get().strip()

            if self.settings.get("remember_launch_options", True):
                self.settings["last_launch_options"] = {
                    "delay": delay_value,
                    "delay_mode": mode,
                    "post_launch": action_var.get(),
                }

            dialog.destroy()
            on_save(result)

        ttk.Button(btn_row, text="Save", style="Accent.TButton",
                   command=save_and_close).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right")

        dialog.update_idletasks()
        w, h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dialog.geometry(f"{w}x{h}+{x}+{y}")

        dialog.grab_set()
        (script_widget or args_entry).focus_set()

    # ---------- Launch logic ----------
    def launch_all(self):
        if not self.programs:
            messagebox.showinfo("Nothing to launch", "Add at least one program first.")
            return
        self.launch_btn.config(state="disabled")
        threading.Thread(target=self._launch_sequence, daemon=True).start()

    @staticmethod
    def _write_temp_script(script_text, shell):
        """Write a script to a temp file so it can be run without nested-quoting issues.

        Passing multi-line scripts inline on a command line means escaping every quote
        inside them, which breaks easily for real-world scripts. Writing to a file and
        running the file avoids that entirely.
        """
        import tempfile
        ext = ".ps1" if shell == "powershell" else ".bat"
        folder = os.path.join(tempfile.gettempdir(), "CPL_Scripts")
        os.makedirs(folder, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=ext, dir=folder, text=False)
        if shell == "powershell":
            body = script_text
            encoding = "utf-8"
        else:
            # cmd needs @echo off so the script body isn't printed back out, and
            # batch files want CRLF line endings
            body = "@echo off\r\n" + script_text.replace("\r\n", "\n").replace("\n", "\r\n")
            encoding = "mbcs"
        # newline="" prevents Python from translating newlines again on Windows,
        # which would otherwise turn our \r\n into \r\r\n
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(body)
        return path

    def _launch_entry(self, entry):
        """Launch one list entry, whether it's a program/file or an inline script."""
        if entry.get("type") == "script":
            shell = entry.get("shell", "powershell")
            script_path = self._write_temp_script(entry.get("script", ""), shell)
            self._launch_program(script_path, "")
        else:
            self._launch_program(entry["path"], entry.get("args", ""))

    @staticmethod
    def _launch_program(path, args=""):
        """Launch a program or script, isolated from CPL's own environment.

        Root cause of launched programs locking CPL's DLLs: PyInstaller's bootloader
        calls SetDllDirectory() pointing at our _internal folder so bundled Python can
        find its DLLs - and per Microsoft's docs, that setting is INHERITED by child
        processes, putting _internal into their DLL search path ahead of System32.
        Launched apps then resolve VCRUNTIME140.dll etc. from our folder and keep them
        locked for as long as they run, blocking CPL updates/uninstalls.

        Fix: temporarily reset the DLL directory to the system default right before
        spawning the child, then restore it afterward so our own process is unaffected.

        Script types get invoked through their proper interpreters, since not all of
        them launch correctly through plain shell association (double-clicking a .ps1,
        for example, opens an editor rather than running it).
        """
        workdir = os.path.dirname(path) or None
        args = (args or "").strip()

        # Strip PyInstaller-injected variables from the environment the child inherits
        env = os.environ.copy()
        for var in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE",
                    "_PYI_PARENT_PROCESS_LEVEL", "PYINSTALLER_RESET_ENVIRONMENT"):
            env.pop(var, None)

        kernel32 = None
        restore_dir = None
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            if getattr(sys, "frozen", False):
                restore_dir = getattr(sys, "_MEIPASS", None)
            # Reset to default DLL search order so the child doesn't inherit _internal
            kernel32.SetDllDirectoryW(None)
        except Exception:
            kernel32 = None

        ext = os.path.splitext(path)[1].lower()
        arg_suffix = f" {args}" if args else ""

        # 'start' via the shell fully detaches the child from our process. First quoted
        # arg is the window title (intentionally empty), second is the target.
        if ext == ".ps1":
            # PowerShell scripts don't run via shell association - invoke explicitly
            cmd = f'start "" powershell -NoProfile -ExecutionPolicy Bypass -File "{path}"{arg_suffix}'
        elif ext == ".vbs":
            # Invoke through wscript explicitly so it runs reliably with arguments
            cmd = f'start "" wscript "{path}"{arg_suffix}'
        else:
            # .exe, .lnk, .bat, .cmd, and anything else with a shell association
            cmd = f'start "" "{path}"{arg_suffix}'

        try:
            subprocess.Popen(
                cmd,
                shell=True,
                cwd=workdir,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        finally:
            # Restore PyInstaller's DLL directory for our own process
            if kernel32 is not None and restore_dir:
                try:
                    kernel32.SetDllDirectoryW(restore_dir)
                except Exception:
                    pass

    def _launch_sequence(self, programs=None):
        if programs is None:
            programs = self.programs
        total = len(programs)
        for i, entry in enumerate(programs, start=1):
            name = entry["name"]
            mode = self._get_delay_mode(entry)
            delay = entry.get("delay", 0) if mode in ("delay", "wait_delay") else 0
            should_wait = mode in ("wait", "wait_delay")
            post_action = entry.get("post_launch", "none")
            needs_windows = should_wait or post_action in ("minimize", "close")

            # Snapshot existing windows so we can tell which ones this program opens
            windows_before = _enum_visible_windows() if needs_windows else set()

            self._set_status(f"[{i}/{total}] Launching '{name}'...")
            try:
                self._launch_entry(entry)
            except Exception as e:
                self._set_status(f"[{i}/{total}] Failed to launch '{name}': {e}")
                time.sleep(2)
                continue

            if should_wait:
                WAIT_TIMEOUT = 60.0
                waited = 0.0
                while waited < WAIT_TIMEOUT:
                    if _enum_visible_windows() - windows_before:
                        break
                    self._set_status(
                        f"[{i}/{total}] Waiting for '{name}' to open... ({int(waited)}s)"
                    )
                    time.sleep(0.5)
                    waited += 0.5
                else:
                    self._set_status(f"[{i}/{total}] '{name}' didn't open a window in time, continuing...")
                    time.sleep(1.5)

            if delay > 0:
                remaining = delay
                while remaining > 0:
                    self._set_status(f"[{i}/{total}] Waiting {remaining:.1f}s after launching '{name}'...")
                    step = 0.1 if remaining >= 0.1 else remaining
                    time.sleep(step)
                    remaining -= step

            if post_action in ("minimize", "close"):
                new_windows = _enum_visible_windows() - windows_before
                if new_windows:
                    verb = "Minimizing" if post_action == "minimize" else "Closing"
                    self._set_status(f"[{i}/{total}] {verb} '{name}'...")
                    _apply_post_launch_action(new_windows, post_action)
                    time.sleep(0.3)

        self._set_status("Done. All programs launched.")
        self.root.after(0, lambda: self.launch_btn.config(state="normal"))

        if self.settings.get("close_after_launch"):
            self.root.after(1500, self.root.destroy)

    def _set_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))

    # ---------- Autostart (launch a specific list on Windows startup only) ----------
    def maybe_run_autostart_sequence(self):
        """Called only when the app was launched via the Windows startup mechanism
        (--autostart on the command line), never for a manual launch."""
        list_name = self.settings.get("autostart_list")
        if not list_name or list_name not in self.lists or not self.lists[list_name]:
            return
        self._show_autostart_countdown(list_name)

    def _show_autostart_countdown(self, list_name, seconds=5):
        dialog = tk.Toplevel(self.root)
        dialog.title("Auto-Launch")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        style_titlebar(dialog, self.theme)

        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, text=f"Auto-launching list:\n\"{list_name}\"",
            font=("Segoe UI", 14, "bold"), justify="center",
        ).pack(pady=(4, 10))

        countdown_var = tk.StringVar()
        ttk.Label(frame, textvariable=countdown_var, font=("Segoe UI", 56, "bold")).pack(pady=(0, 10))

        ttk.Label(frame, text="Click Cancel to stop this.", font=("Segoe UI", 10)).pack(pady=(0, 16))

        state = {"cancelled": False}

        def do_cancel():
            state["cancelled"] = True
            dialog.destroy()

        ttk.Button(frame, text="Cancel", style="Accent.TButton", command=do_cancel).pack(ipadx=24, ipady=8)
        dialog.protocol("WM_DELETE_WINDOW", do_cancel)

        # Size the dialog to its contents (correct at any DPI scaling, so nothing gets
        # clipped) and center on screen. winfo_reqwidth/reqheight report the layout's
        # requested size, which is reliable before the window is mapped - unlike
        # winfo_width/height, which can return bogus values during the busy boot phase
        # (that's what was pushing this to the top-left corner before).
        dialog.update_idletasks()
        w = dialog.winfo_reqwidth()
        h = dialog.winfo_reqheight()
        x = (dialog.winfo_screenwidth() - w) // 2
        y = (dialog.winfo_screenheight() - h) // 2
        dialog.geometry(f"{w}x{h}+{x}+{y}")
        # Re-assert shortly after mapping, in case anything (window manager, DPI
        # adjustment) moved it during initial display
        dialog.after(50, lambda: dialog.geometry(f"{w}x{h}+{x}+{y}"))

        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(200, lambda: dialog.attributes("-topmost", False))
        dialog.grab_set()
        dialog.focus_force()

        def tick(remaining):
            if state["cancelled"]:
                return
            if remaining <= 0:
                dialog.destroy()
                self._run_autostart_launch(list_name)
                return
            countdown_var.set(str(remaining))
            dialog.after(1000, lambda: tick(remaining - 1))

        tick(seconds)

    def _run_autostart_launch(self, list_name):
        programs = self.lists.get(list_name, [])
        if not programs:
            return
        self.launch_btn.config(state="disabled")
        threading.Thread(target=self._launch_sequence, args=(list(programs),), daemon=True).start()


def set_window_icon(window, ico_path):
    """Set the window's title bar and taskbar/Alt-Tab icons directly via the Windows API.

    Tkinter's built-in iconbitmap() on Windows tends to grab a single frame from the
    .ico file and stretch it for every context, which looks blurry in the taskbar even
    when the .ico file itself contains larger sizes. Loading each size explicitly and
    sending WM_SETICON avoids that.
    """
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())

        LR_LOADFROMFILE = 0x00000010
        IMAGE_ICON = 1
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        hicon_small = ctypes.windll.user32.LoadImageW(0, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        hicon_big = ctypes.windll.user32.LoadImageW(0, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)

        if hicon_small:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        if hicon_big:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
    except Exception:
        pass  # Not on Windows, or something went wrong - not critical


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Per-monitor DPI awareness
    except Exception:
        pass  # Not on Windows, or older Windows without shcore - safe to skip

    root = tk.Tk()
    root.title("Custom Program Launcher")

    try:
        root.iconbitmap(resource_path("app_icon.ico"))  # fallback for non-Windows/edge cases
    except Exception:
        pass  # Icon file not found - not critical, app still runs fine

    set_window_icon(root, resource_path("app_icon.ico"))

    theme = get_windows_theme()
    sv_ttk.set_theme(theme)

    app = ProgramLauncherApp(root)
    style_titlebar(root, theme)

    if "--autostart" in sys.argv:
        root.after(600, app.maybe_run_autostart_sequence)

    root.mainloop()


if __name__ == "__main__":
    main()
