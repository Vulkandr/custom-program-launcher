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
    """Build the command line to launch this app, whether running as a script or a frozen exe."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


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
        self.root.minsize(660, 420)
        self._set_initial_geometry()
        self.root.resizable(True, True)

        self.programs = []  # list of dicts: {"path": str, "delay": float, "name": str}
        self.lists = {}     # dict of list_name -> list of program dicts
        self.current_list_name = "Default"
        self.theme = get_windows_theme()

        # Settings (persisted alongside the program lists)
        self.settings = {"start_on_boot": False, "close_after_launch": False, "default_delay": 3.0}
        self.start_on_boot_var = tk.BooleanVar(value=False)
        self.close_after_launch_var = tk.BooleanVar(value=False)

        # State for the hover-scroll effect on long Path values
        self._marquee_item = None
        self._marquee_after_id = None
        self._marquee_original = None
        self._marquee_full = None
        self._marquee_offset = 0
        self._marquee_col_width = 0

        self._build_ui()
        self._load_config()

    def _set_initial_geometry(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # Scale to a comfortable fraction of the screen, clamped between the minsize and a sane cap
        width = max(660, min(690, int(screen_w * 0.4)))
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
        settings_menu.add_command(label=self._default_delay_label(), command=self.edit_default_delay)
        self.settings_menu = settings_menu
        self._default_delay_menu_index = settings_menu.index("end")
        settings_menu.add_separator()
        settings_menu.add_command(label="More Settings...", command=self.open_settings_window)
        settings_menu.add_separator()
        settings_menu.add_command(label=f"Version {APP_VERSION}", command=open_repo_link)

        return settings_menu

    def _default_delay_label(self):
        return f"Default Delay: {self.settings.get('default_delay', 3.0):.1f}s"

    def edit_default_delay(self):
        new_delay = simpledialog.askfloat(
            "Default Delay",
            "Default delay (in seconds) to pre-fill when adding a new program:",
            initialvalue=self.settings.get("default_delay", 3.0),
            minvalue=0.0,
        )
        if new_delay is None:
            return
        self.settings["default_delay"] = new_delay
        self.settings_menu.entryconfigure(self._default_delay_menu_index, label=self._default_delay_label())
        self._save_config()

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

    def open_settings_window(self):
        # Placeholder for a future, fuller settings window - the checkboxes above remain
        # the source of truth so this can be expanded later without breaking anything.
        messagebox.showinfo(
            "Settings",
            "A fuller settings window is planned for a future update.\n\n"
            "For now, use the checkboxes in this menu."
        )

    # ---------- UI ----------
    def _build_ui(self):
        container = ttk.Frame(self.root, padding=0)
        container.pack(fill="both", expand=True)

        settings_menu = self._build_settings_menu()

        top_row = ttk.Frame(container)
        top_row.pack(fill="x", padx=10, pady=(10, 4))
        top_row.columnconfigure(0, weight=1)
        top_row.columnconfigure(2, weight=1)

        list_frame = ttk.Frame(top_row)
        list_frame.grid(row=0, column=1)

        ttk.Label(list_frame, text="List:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.list_var = tk.StringVar()
        self.list_combo = ttk.Combobox(list_frame, textvariable=self.list_var, state="readonly", width=25)
        self.list_combo.pack(side="left", padx=(5, 10))
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

        columns = ("name", "path", "delay")
        self.tree = ttk.Treeview(top_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Program")
        self.tree.heading("path", text="Path")
        self.tree.heading("delay", text="Delay")
        self.tree.column("name", width=145, minwidth=145, stretch=False)
        self.tree.column("path", width=260, stretch=True)
        self.tree.column("delay", width=50, minwidth=50, anchor="center", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)

        btn_frame_row1 = ttk.Frame(container)
        btn_frame_row1.pack(pady=(0, 4))
        ttk.Button(btn_frame_row1, text="Choose Installed Program", command=self.add_from_installed).pack(side="left", padx=5)
        ttk.Button(btn_frame_row1, text="Browse for File...", command=self.add_program).pack(side="left", padx=5)
        ttk.Button(btn_frame_row1, text="Remove Selected", command=self.remove_program).pack(side="left", padx=5)

        btn_frame_row2 = ttk.Frame(container)
        btn_frame_row2.pack(pady=(0, 10))
        ttk.Button(btn_frame_row2, text="Move Up", command=self.move_up).pack(side="left", padx=5)
        ttk.Button(btn_frame_row2, text="Move Down", command=self.move_down).pack(side="left", padx=5)
        ttk.Button(btn_frame_row2, text="Edit Delay", command=self.edit_delay).pack(side="left", padx=5)

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

    def _refresh_tree(self):
        self._stop_marquee()
        self.tree.delete(*self.tree.get_children())
        for entry in self.programs:
            self.tree.insert("", "end", values=(entry["name"], entry["path"], f"{entry['delay']}s"))

    def _get_tree_font(self):
        style = ttk.Style()
        font_spec = style.lookup("Treeview", "font") or "TkDefaultFont"
        try:
            return tkfont.nametofont(font_spec)
        except tk.TclError:
            return tkfont.Font(font=font_spec)

    # ---------- Path hover-scroll effect ----------
    def _on_tree_motion(self, event):
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

        full_path = self.programs[idx]["path"]
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
        self._save_config()
        self.status_var.set(f"Switched to list '{self.current_list_name}'.")

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
        self.current_list_name = new_name
        self._refresh_list_combo()
        self._save_config()

    def delete_list(self):
        if len(self.lists) <= 1:
            messagebox.showinfo("Can't delete", "You need at least one list.")
            return
        if not messagebox.askyesno("Delete List", f"Delete the list '{self.current_list_name}'? This can't be undone."):
            return
        del self.lists[self.current_list_name]
        self.current_list_name = next(iter(self.lists))
        self.programs = self.lists[self.current_list_name]
        self._refresh_list_combo()
        self._refresh_tree()
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
        picker.title("Choose Installed Program")
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
        default_delay = self.settings.get("default_delay", 3.0)
        delay = simpledialog.askfloat(
            "Delay",
            f"Delay in seconds to wait after launching '{name}'\n"
            f"(gives it time to boot up before moving to the next program):",
            initialvalue=default_delay, minvalue=0.0,
        )
        if delay is None:
            delay = default_delay
        self.programs.append({"name": name, "path": path, "delay": delay})
        self._refresh_tree()
        self._save_config()

    # ---------- Program list management ----------
    def add_program(self):
        path = filedialog.askopenfilename(
            title="Select a program",
            filetypes=[("Executables/Shortcuts", "*.exe;*.lnk"), ("All files", "*.*")],
        )
        if not path:
            return

        name = os.path.splitext(os.path.basename(path))[0]
        self.root.after(150, lambda: self._prompt_delay_and_add(name, path))

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

    def edit_delay(self):
        idx = self._get_selected_index()
        if idx is None:
            messagebox.showinfo("No selection", "Select a program to edit first.")
            return
        entry = self.programs[idx]
        delay = simpledialog.askfloat(
            "Edit Delay",
            f"Delay in seconds to wait after launching '{entry['name']}':",
            initialvalue=entry["delay"], minvalue=0.0,
        )
        if delay is not None:
            entry["delay"] = delay
            self._refresh_tree()
            self._save_config()

    # ---------- Launch logic ----------
    def launch_all(self):
        if not self.programs:
            messagebox.showinfo("Nothing to launch", "Add at least one program first.")
            return
        self.launch_btn.config(state="disabled")
        threading.Thread(target=self._launch_sequence, daemon=True).start()

    def _launch_sequence(self):
        total = len(self.programs)
        for i, entry in enumerate(self.programs, start=1):
            delay = entry["delay"]
            name = entry["name"]

            self._set_status(f"[{i}/{total}] Launching '{name}'...")
            try:
                os.startfile(entry["path"])
            except Exception as e:
                self._set_status(f"[{i}/{total}] Failed to launch '{name}': {e}")
                time.sleep(2)
                continue

            if delay > 0:
                remaining = delay
                while remaining > 0:
                    self._set_status(f"[{i}/{total}] Waiting {remaining:.1f}s after launching '{name}'...")
                    step = 0.1 if remaining >= 0.1 else remaining
                    time.sleep(step)
                    remaining -= step

        self._set_status("Done. All programs launched.")
        self.root.after(0, lambda: self.launch_btn.config(state="normal"))

        if self.settings.get("close_after_launch"):
            self.root.after(1500, self.root.destroy)

    def _set_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))


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

    root.mainloop()


if __name__ == "__main__":
    main()
