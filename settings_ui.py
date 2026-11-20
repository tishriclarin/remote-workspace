"""Native desktop settings for SSH Workspace."""

import json
import os
import re
import shutil
import subprocess
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, font, ttk

import ssh_clients as clients

LIGHT = {
    "bg": "#F1F5F9", "paper": "#FFFFFF", "ink": "#15263C", "muted": "#475D74",
    "line": "#D7E1EC", "nav": "#10243A", "nav_text": "#B9CADB",
    "nav_active": "#203B54", "mint": "#63EAC7", "accent": "#087965",
    "accent_hot": "#086653", "error": "#A42832", "primary_fg": "#FFFFFF",
}
DARK = {
    "bg": "#111B29", "paper": "#1A293C", "ink": "#F1F6FC", "muted": "#AEC0D5",
    "line": "#3B5069", "nav": "#0A1421", "nav_text": "#ADC0D7",
    "nav_active": "#233952", "mint": "#68EAC5", "accent": "#65DFBD",
    "accent_hot": "#7DEBCD", "error": "#FFAFB2", "primary_fg": "#102B28",
}
APPEARANCES = {"Follow system": "system", "Light": "light", "Dark": "dark"}
ERRORS = (OSError, ValueError, subprocess.SubprocessError)


def desktop_appearance():
    if shutil.which("gdbus"):
        try:
            result = subprocess.run([
                "gdbus", "call", "--session", "--dest", "org.freedesktop.portal.Desktop",
                "--object-path", "/org/freedesktop/portal/desktop", "--method",
                "org.freedesktop.portal.Settings.Read", "org.freedesktop.appearance", "color-scheme",
            ], text=True, capture_output=True, timeout=1, check=True)
            match = re.search(r"uint32 ([12])\b", result.stdout)
            if match:
                return "dark" if match[1] == "1" else "light"
        except ERRORS:
            pass
    return "dark" if "dark" in os.environ.get("GTK_THEME", "").lower() else "light"


def current_appearance(preference):
    if preference in ("dark", "light"):
        return preference
    return desktop_appearance()


class SettingsWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("SSH Workspace")
        self.root.geometry("960x750")
        self.root.minsize(780, 730)
        self.state = json.loads(clients.read_state())
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.job = None
        self.choice = tk.StringVar()
        self.message = tk.StringVar()
        self.labels = {}
        self.opener = None
        self.page = ""
        self.apply_theme("Settings")

    def apply_theme(self, page):
        palette = current_appearance(self.state.get("appearance", "system"))
        self.colors = DARK if palette == "dark" else LIGHT
        self.root.configure(bg=self.colors["bg"])
        for child in self.root.winfo_children():
            child.destroy()
        self.setup_style()
        root = self.root
        self.root.columnconfigure(0, minsize=214)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.navigation = tk.Frame(root, width=214, bg=self.colors["nav"])
        self.navigation.grid(row=0, column=0, sticky="ns")
        self.navigation.pack_propagate(False)
        self.content = tk.Frame(root, bg=self.colors["bg"])
        self.content.grid(row=0, column=1, sticky="nsew", padx=34, pady=28)
        self.content.columnconfigure(0, weight=1)

        self.label(self.navigation, ">_", 19, self.colors["mint"], self.colors["nav"], bold=True).pack(
            anchor="w", padx=22, pady=(30, 7))
        self.label(self.navigation, "SSH Workspace", 15, "white", self.colors["nav"], bold=True).pack(
            anchor="w", padx=22, pady=(0, 25))
        self.nav_buttons = {}
        for name in ("Settings", "General Settings"):
            button = tk.Button(
                self.navigation, text=name, command=lambda target=name: self.open_page(target),
                padx=13, pady=10, anchor="w", relief="flat", borderwidth=0,
                highlightthickness=1, highlightcolor=self.colors["mint"], takefocus=True,
                font=(self.sans, 10, "bold"), cursor="hand2",
            )
            button.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[name] = button

        self.open_page(page)

    def setup_style(self):
        families = set(font.families(self.root))
        self.sans = next((name for name in ("Inter", "DejaVu Sans", "Noto Sans") if name in families), "TkDefaultFont")
        self.mono = next((name for name in ("IBM Plex Mono", "DejaVu Sans Mono") if name in families), "TkFixedFont")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Workspace.TButton", font=(self.sans, 10, "bold"), foreground=self.colors["ink"],
                        background=self.colors["paper"], padding=(12, 7), bordercolor=self.colors["line"],
                        lightcolor=self.colors["paper"], darkcolor=self.colors["paper"],
                        focuscolor=self.colors["accent"])
        style.map("Workspace.TButton", background=[("active", self.colors["bg"])])
        style.configure("Primary.Workspace.TButton", foreground=self.colors["primary_fg"], background=self.colors["accent"],
                        bordercolor=self.colors["accent"])
        style.map("Primary.Workspace.TButton", background=[
            ("disabled", self.colors["muted"]), ("active", self.colors["accent_hot"]),
        ])
        style.configure("Workspace.TCombobox", font=(self.sans, 10), padding=6, arrowsize=14,
                        background=self.colors["paper"], bordercolor=self.colors["line"], foreground=self.colors["ink"],
                        arrowcolor=self.colors["ink"], lightcolor=self.colors["paper"], darkcolor=self.colors["paper"])
        style.map("Workspace.TCombobox", fieldbackground=[("readonly", self.colors["paper"])],
                  foreground=[("readonly", self.colors["ink"])])
        self.root.option_add("*TCombobox*Listbox.font", (self.sans, 10))
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.colors["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", self.colors["primary_fg"])
        self.root.option_add("*TCombobox*Listbox.background", self.colors["paper"])
        self.root.option_add("*TCombobox*Listbox.foreground", self.colors["ink"])
        style.configure("Workspace.TEntry", fieldbackground=self.colors["paper"],
                        foreground=self.colors["ink"], bordercolor=self.colors["line"])
        style.configure("Workspace.Vertical.TScrollbar", background=self.colors["line"],
                        troughcolor=self.colors["paper"], arrowcolor=self.colors["ink"],
                        bordercolor=self.colors["paper"], lightcolor=self.colors["line"],
                        darkcolor=self.colors["line"])

    def label(self, parent, text, size=10, color=None, bg=None, *, bold=False, **options):
        return tk.Label(parent, text=text, font=(self.sans, size, "bold" if bold else "normal"),
                        fg=color or self.colors["ink"], bg=bg or self.colors["bg"],
                        anchor="w", justify="left", **options)

    def button(self, parent, text, command, primary=False):
        style = "Primary.Workspace.TButton" if primary else "Workspace.TButton"
        return ttk.Button(parent, text=text, command=command, style=style)

    def card(self, parent, bg=None):
        outer = tk.Frame(parent, bg=bg or self.colors["paper"], highlightthickness=1,
                         highlightbackground=self.colors["line"], padx=20, pady=14)
        return outer

    def open_page(self, name):
        self.page = name
        self.opener = None
        self.content.rowconfigure(2, weight=0)
        for child in self.content.winfo_children():
            child.destroy()
        selected = "General Settings" if name == "Activity history" else name
        for label, button in self.nav_buttons.items():
            button.configure(bg=self.colors["nav_active"] if label == selected else self.colors["nav"],
                             fg="white" if label == selected else self.colors["nav_text"],
                             activebackground=self.colors["nav_active"], activeforeground="white",
                             highlightbackground=self.colors["nav"])
        descriptions = {
            "Settings": "Choose the native OpenSSH client used for local diagnostics.",
            "General Settings": "Set defaults for new hosts, manage the client cache, and review local activity.",
            "Activity history": "These events come from the system journal visible to your account.",
        }
        self.label(self.content, name, 28, bold=True).grid(sticky="ew")
        self.label(self.content, descriptions[name], color=self.colors["muted"], wraplength=490).grid(
            sticky="ew", pady=(5, 18))
        if name == "Settings":
            self.main_page()
        elif name == "General Settings":
            self.general_page()
        else:
            self.history_page()
        self.status = self.label(self.content, "", color=self.colors["muted"], textvariable=self.message, wraplength=500)
        self.status.grid(sticky="ew", pady=(10, 0))

    def main_page(self):
        panel = self.card(self.content)
        panel.grid(sticky="ew")
        self.label(panel, "OpenSSH client", 13, bg=self.colors["paper"], bold=True).pack(anchor="w")
        self.opener = ttk.Combobox(panel, textvariable=self.choice, state="readonly",
                                   style="Workspace.TCombobox", font=(self.sans, 10), height=10)
        self.opener.pack(fill="x", pady=(8, 8))
        self.opener.bind("<<ComboboxSelected>>", lambda _: self.perform(
            lambda: clients.select(self.labels[self.choice.get()]), "OpenSSH client saved."))
        self.label(panel, "Latest available stable uses the newest stable client available on this machine.",
                   color=self.colors["muted"], bg=self.colors["paper"], wraplength=450).pack(anchor="w")
        self.render_clients()

    def render_clients(self):
        self.labels = {"Latest available stable": "latest", "System client on PATH": "system"}
        for client in self.state["cache"]:
            label = f'{client["version"]} · {client["track"]} · {client["path"]}'
            self.labels[label] = client["id"]
        if self.opener is not None:
            self.opener.configure(values=list(self.labels))
            chosen = next((label for label, value in self.labels.items()
                           if value == self.state["selection"]), "Selected client unavailable")
            self.choice.set(chosen)

    def general_page(self):
        appearance = self.card(self.content)
        appearance.grid(sticky="ew", pady=(0, 13))
        row = tk.Frame(appearance, bg=self.colors["paper"])
        row.pack(fill="x")
        self.label(row, "Appearance", 13, bg=self.colors["paper"], bold=True).pack(side="left")
        mode = self.state.get("appearance", "system")
        labels = {value: label for label, value in APPEARANCES.items()}
        selector = ttk.Combobox(row, state="readonly", values=list(APPEARANCES), width=15,
                                style="Workspace.TCombobox", font=(self.sans, 10))
        selector.set(labels.get(mode, "Follow system"))
        selector.pack(side="right")

        def switch(_):
            text = editor.get("1.0", "end-1c")
            choice = APPEARANCES[selector.get()]
            try:
                self.state = clients.change_state(lambda state: state.update(appearance=choice))
            except ERRORS as error:
                selector.set(labels.get(mode, "Follow system"))
                self.announce(str(error), True)
                return
            self.draft = text
            self.apply_theme("General Settings")

        selector.bind("<<ComboboxSelected>>", switch)
        defaults = self.card(self.content)
        defaults.grid(sticky="ew", pady=(0, 13))
        self.label(defaults, "New host defaults", 13, bg=self.colors["paper"], bold=True).pack(anchor="w")
        self.label(defaults, "JSON settings apply when a profile is created.", color=self.colors["muted"],
                   bg=self.colors["paper"]).pack(anchor="w", pady=(3, 6))
        editor = tk.Text(defaults, width=42, height=5, wrap="none", font=(self.mono, 10), relief="flat",
                         background=self.colors["bg"], foreground=self.colors["ink"], insertbackground=self.colors["ink"],
                         padx=10, pady=7, highlightthickness=1, highlightbackground=self.colors["line"],
                         highlightcolor=self.colors["accent"])
        editor.pack(fill="x")
        draft = getattr(self, "draft", None)
        editor.insert("1.0", draft if draft is not None else json.dumps(self.state.get("profile_defaults", {}), indent=2))
        self.draft = None
        self.button(defaults, "Save defaults", lambda: self.perform(
            lambda: clients.save_profile_defaults(editor.get("1.0", "end")), "Defaults saved."), True).pack(
                anchor="w", pady=(8, 0))
        cache = self.card(self.content)
        cache.grid(sticky="ew", pady=(0, 13))
        self.label(cache, "Native clients", 13, bg=self.colors["paper"], bold=True).pack(anchor="w")
        row = tk.Frame(cache, bg=self.colors["paper"])
        row.pack(anchor="w", pady=(7, 0))
        self.button(row, "Refresh cache", lambda: self.background(
            clients.refresh_cache, "Checking installed clients…", "Client cache refreshed.")).pack(side="left", padx=(0, 6))
        self.button(row, "Get stable client", lambda: self.background(
            clients.fetch_native, "Fetching native client from APT…", "Native client updated.")).pack(side="left", padx=(0, 6))
        self.button(row, "Add client…", self.add_client_window).pack(side="left")
        self.button(self.content, "View activity history", lambda: self.open_page("Activity history")).grid(sticky="w")

    def history_page(self):
        self.content.rowconfigure(2, weight=1)
        panel = self.card(self.content)
        panel.grid(sticky="nsew", pady=(0, 12))
        text = tk.Text(panel, width=36, height=12, wrap="word", font=(self.mono, 10), relief="flat",
                       background=self.colors["paper"], foreground=self.colors["ink"], highlightthickness=0)
        scroll = ttk.Scrollbar(panel, command=text.yview, style="Workspace.Vertical.TScrollbar")
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        try:
            events = clients.read_history()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            events = str(error)
        text.insert("1.0", events)
        text.configure(state="disabled")
        row = tk.Frame(self.content, bg=self.colors["bg"])
        row.grid(sticky="w")
        self.button(row, "Back to General Settings", lambda: self.open_page("General Settings")).pack(
            side="left", padx=(0, 6))
        self.button(row, "Refresh", lambda: self.open_page("Activity history")).pack(side="left")

    def add_client_window(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Add native client")
        dialog.transient(self.root)
        dialog.configure(bg=self.colors["bg"])
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        frame = self.card(dialog)
        frame.pack(fill="both", expand=True, padx=18, pady=18)
        self.label(frame, "Add native client", 19, bg=self.colors["paper"], bold=True).pack(anchor="w")
        self.label(frame, "Choose a trusted OpenSSH executable and assign its release track.",
                   color=self.colors["muted"], bg=self.colors["paper"], wraplength=370).pack(anchor="w", pady=(4, 13))
        path = tk.StringVar()
        track = tk.StringVar(value="stable")
        self.label(frame, "Executable", bg=self.colors["paper"], bold=True).pack(anchor="w")
        row = tk.Frame(frame, bg=self.colors["paper"])
        row.pack(fill="x", pady=(4, 10))
        entry = ttk.Entry(row, width=35, textvariable=path, font=(self.sans, 10), style="Workspace.TEntry")
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)

        def browse():
            chosen = filedialog.askopenfilename(title="Select an OpenSSH executable", parent=dialog)
            if chosen:
                path.set(chosen)

        self.button(row, "Browse…", browse).pack(side="left")
        self.label(frame, "Release track", bg=self.colors["paper"], bold=True).pack(anchor="w")
        ttk.Combobox(frame, state="readonly", textvariable=track, values=clients.TRACKS,
                     style="Workspace.TCombobox").pack(fill="x", pady=(4, 13))

        def add():
            executable, channel = path.get().strip(), track.get()
            if not executable:
                entry.focus_set()
                return
            if self.background(lambda: clients.register(executable, channel),
                               "Checking native client…", "Native client registered."):
                dialog.destroy()

        action = tk.Frame(frame, bg=self.colors["paper"])
        action.pack(anchor="e")
        self.button(action, "Cancel", dialog.destroy).pack(side="left", padx=(0, 6))
        self.button(action, "Add client", add, True).pack(side="left")
        entry.focus_set()

    def announce(self, message, error=False):
        self.message.set(message)
        self.status.configure(fg=self.colors["error"] if error else self.colors["muted"])

    def perform(self, operation, success):
        try:
            self.state = operation()
            self.render_clients()
            self.announce(success)
        except ERRORS as error:
            self.render_clients()
            self.announce(str(error), True)

    def background(self, operation, pending, success):
        if self.job is not None:
            self.announce("Wait for the current client operation to finish.")
            return False
        self.announce(pending)
        self.job = self.pool.submit(operation)

        def finish():
            if not self.job.done():
                self.root.after(100, finish)
                return
            job, self.job = self.job, None
            self.perform(job.result, success)

        self.root.after(100, finish)
        return True

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.pool.shutdown(wait=False)


def show_ui():
    SettingsWindow(tk.Tk()).run()
