from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from app import score_ceos as scoring


ROOT = Path(__file__).resolve().parents[1]
MODELS = {"ChatGPT": ("gpt",), "DeepSeek": ("deepseek",), "Both": scoring.PROVIDERS}
ENV_NAMES = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY")
KEY_FIELDS = {"openai_key": "OPENAI_API_KEY", "deepseek_key": "DEEPSEEK_API_KEY"}
CSV_ENCODINGS = {"Auto": "auto", "UTF-8": "utf-8-sig", "UTF-16": "utf-16",
                 "UTF-16 LE": "utf-16-le", "UTF-16 BE": "utf-16-be", "Windows-1252": "cp1252",
                 "GB18030 / GBK": "gb18030", "MS-DOS (CP437)": "cp437", "ISO-8859-1": "latin-1"}


def local_credentials(root):
    values = {name: os.getenv(name, "") for name in ENV_NAMES}
    path = root / "config" / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.strip().partition("=")
            if separator and name.strip() in ENV_NAMES:
                value = value.strip()
                if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
                    value = value[1:-1]
                values[name.strip()] = value
    return values


def portable_path(path, root):
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def resolve_path(value, root):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def save_preferences(root, fields, remember_keys):
    secret_fields = {"openai_key", "deepseek_key", "azure_key"}
    values = {name: value for name, value in fields.items() if name not in secret_fields}
    for name in ("input", "output"):
        values[name] = portable_path(resolve_path(values[name], root), root)
    values["remember_keys"] = remember_keys
    scoring.atomic_text(root / "config" / "settings.local.json", json.dumps(values, indent=2) + "\n")
    if remember_keys:
        credentials = {name: fields[field].strip() for field, name in KEY_FIELDS.items()}
        if any("\n" in value or "\r" in value for value in credentials.values()):
            raise ValueError("Connection fields must each contain a single line")
        scoring.atomic_text(root / "config" / ".env", "".join(f"{name}={value}\n" for name, value in credentials.items()))
    else:
        path = root / "config" / ".env"
        if path.is_file():
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            secret_names = {KEY_FIELDS[name] for name in secret_fields if name in KEY_FIELDS}
            remaining = [line for line in lines if line.partition("=")[0].strip() not in secret_names]
            scoring.atomic_text(path, "".join(line + "\n" for line in remaining))


class ScoringApp:
    def __init__(self, window, root=ROOT):
        self.window, self.root = window, root.resolve()
        self.config = scoring.load_config(self.root / "config" / "config.toml")
        self.fields, self.controls = {}, []
        self.events = queue.Queue()
        self.thread = self.loop = self.task = None
        self.stopping = threading.Event()
        self.closing = False
        self.busy = False
        self.current_credentials = {}
        defaults = {
            "input": "data/sp500_ceos.csv", "output": "outputs", "scores": "10",
            "provider": "ChatGPT", "dimension": "extraversion",
            "openai_model": self.config["providers"]["gpt"]["model"],
            "deepseek_model": self.config["providers"]["deepseek"]["model"],
            "gpt_concurrency": "5", "deepseek_concurrency": "50", "timeout": "60",
            "max_tokens": "1024", "delay": "1.0", "input_encoding": "Auto"}
        path = self.root / "config" / "settings.local.json"
        preferences = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        defaults.update({k: v for k, v in preferences.items() if k in defaults and isinstance(v, str)})
        credentials = local_credentials(self.root)
        for field, name in KEY_FIELDS.items():
            defaults[field] = credentials[name] or defaults.get(field, "")
        for name in ("input", "output"):
            defaults[name] = str(resolve_path(defaults[name], self.root))
        self.defaults = defaults
        self.remember = tk.BooleanVar(value=bool(preferences.get("remember_keys", False)))
        window.title("CEO Big Five Scoring")
        screen_height = window.winfo_screenheight()
        window.geometry(f"940x{min(660, screen_height - 100)}")
        window.minsize(820, 540)
        style = ttk.Style(window)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        outer = ttk.Frame(window, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        ttk.Label(outer, text="CEO Big Five Scoring", font=("Segoe UI", 19, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 12))
        self.tabs = ttk.Notebook(outer)
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self.run_tab, self.connection_tab, self.advanced_tab, self.log_tab = [
            ttk.Frame(self.tabs, padding=14) for _ in range(4)]
        for tab, title in ((self.run_tab, "Run"), (self.connection_tab, "Connections"),
                           (self.advanced_tab, "Advanced"), (self.log_tab, "Progress")):
            self.tabs.add(tab, text=title)
            tab.columnconfigure(1, weight=1)
        self.entry(self.run_tab, 0, "CEO input CSV", "input", browse="file")
        self.entry(self.run_tab, 1, "Results folder", "output", browse="folder")
        self.entry(self.run_tab, 2, "Valid scores per CEO / trait", "scores")
        model_box = ttk.LabelFrame(self.run_tab, text="Models", padding=10)
        model_box.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
        selected = preferences.get("providers", MODELS.get(defaults["provider"], ("gpt",)))
        self.providers = {name: tk.BooleanVar(value=name in selected) for name in scoring.PROVIDERS}
        for index, (name, label) in enumerate((("gpt", "ChatGPT"), ("deepseek", "DeepSeek"))):
            self.add_control(ttk.Checkbutton(model_box, text=label, variable=self.providers[name])).grid(
                row=0, column=index, padx=(0, 28), sticky="w")
        trait_box = ttk.LabelFrame(self.run_tab, text="Personality traits", padding=10)
        trait_box.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        selected = preferences.get("dimensions", scoring.DIMENSIONS if defaults["dimension"] == "all"
                                   else (defaults["dimension"],))
        self.dimensions = {name: tk.BooleanVar(value=name in selected) for name in scoring.DIMENSIONS}
        for index, (name, variable) in enumerate(self.dimensions.items()):
            self.add_control(ttk.Checkbutton(trait_box, text=name.capitalize(), variable=variable)).grid(
                row=index // 3, column=index % 3, padx=(0, 22), pady=3, sticky="w")
        trait_actions = ttk.Frame(trait_box)
        trait_actions.grid(row=1, column=2, sticky="w")
        self.add_control(ttk.Button(trait_actions, text="Select all", command=lambda: self.select_traits(True))).pack(side="left")
        self.add_control(ttk.Button(trait_actions, text="Clear", command=lambda: self.select_traits(False))).pack(side="left", padx=6)
        self.entry(self.connection_tab, 0, "DeepSeek API key", "deepseek_key", secret=True)
        self.entry(self.connection_tab, 1, "DeepSeek model", "deepseek_model")
        ttk.Separator(self.connection_tab).grid(row=2, column=0, columnspan=3, sticky="ew", pady=10)
        self.entry(self.connection_tab, 3, "OpenAI API key", "openai_key", secret=True)
        self.entry(self.connection_tab, 4, "OpenAI model", "openai_model")
        self.add_control(ttk.Checkbutton(self.connection_tab, text="Save API keys locally",
                                        variable=self.remember)).grid(row=5, column=0, columnspan=3, sticky="w", pady=10)
        advanced = self.advanced_tab
        self.entry(advanced, 0, "ChatGPT parallel requests", "gpt_concurrency")
        self.entry(advanced, 1, "DeepSeek parallel requests", "deepseek_concurrency")
        self.entry(advanced, 2, "Request timeout (seconds)", "timeout")
        self.entry(advanced, 3, "Maximum response tokens", "max_tokens")
        self.entry(advanced, 4, "Pause after a request (seconds)", "delay")
        self.entry(advanced, 5, "CSV encoding", "input_encoding", choices=tuple(CSV_ENCODINGS))
        self.collection_status = tk.StringVar(value="Ready")
        ttk.Label(self.log_tab, textvariable=self.collection_status, wraplength=770).pack(anchor="w")
        self.bar = ttk.Progressbar(self.log_tab, maximum=100)
        self.bar.pack(fill="x", pady=10)
        self.log = scrolledtext.ScrolledText(self.log_tab, state="disabled", wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(outer, textvariable=self.status, wraplength=880).grid(row=2, column=0, sticky="w", pady=10)
        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky="ew")
        self.add_control(ttk.Button(actions, text="Save settings", command=self.save)).pack(side="left", padx=(0, 8))
        self.check_button = self.add_control(ttk.Button(actions, text="Check settings", command=self.check))
        self.check_button.pack(side="left")
        self.start_button = self.add_control(ttk.Button(actions, text="Start / Resume", command=self.start))
        self.start_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left")
        ttk.Button(actions, text="Open results", command=self.open_results).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = window.after(100, self.poll)

    def add_control(self, widget, state="normal"):
        self.controls.append((widget, state))
        return widget

    def entry(self, parent, row, label, name, choices=None, secret=False, browse=None):
        variable = tk.StringVar(value=self.defaults.get(name, ""))
        self.fields[name] = variable
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=6)
        if choices:
            widget = ttk.Combobox(parent, textvariable=variable, values=choices, state="readonly")
        else:
            widget = ttk.Entry(parent, textvariable=variable, show="*" if secret else "")
        self.add_control(widget, "readonly" if choices else "normal")
        widget.grid(row=row, column=1, sticky="ew", pady=6)
        setattr(self, f"{name}_widget", widget)
        if browse:
            button = ttk.Button(parent, text="Browse...", command=lambda: self.browse(name, browse))
            self.add_control(button).grid(row=row, column=2, padx=(8, 0), pady=6)

    def browse(self, name, kind):
        initial = resolve_path(self.fields[name].get(), self.root)
        options = {"parent": self.window, "initialdir": str(initial if initial.is_dir() else initial.parent)}
        result = filedialog.askdirectory(**options) if kind == "folder" else filedialog.askopenfilename(
            **options, filetypes=(("CSV files", "*.csv"), ("All files", "*.*")))
        if result:
            self.fields[name].set(result)

    def select_traits(self, selected):
        for variable in self.dimensions.values():
            variable.set(selected)

    def plan(self, check_only=False):
        values = {name: variable.get().strip() for name, variable in self.fields.items()}
        providers = tuple(name for name, variable in self.providers.items() if variable.get())
        dimensions = tuple(name for name, variable in self.dimensions.items() if variable.get())
        if not providers:
            raise ValueError("Select at least one model")
        if not dimensions:
            raise ValueError("Select at least one personality trait")
        values.update(providers=list(providers), dimensions=list(dimensions))
        config = copy.deepcopy(self.config)
        run = config["run"]
        run.update(mode="research", valid_scores_per_ceo=int(values["scores"]),
                   input_encoding=CSV_ENCODINGS[values["input_encoding"]],
                   max_tokens=int(values["max_tokens"]), timeout_seconds=float(values["timeout"]),
                   request_delay_seconds=float(values["delay"]))
        gpt, ds = config["providers"]["gpt"], config["providers"]["deepseek"]
        gpt["concurrency"], ds["concurrency"] = int(values["gpt_concurrency"]), int(values["deepseek_concurrency"])
        gpt.update(adapter="openai_compatible", model=values["openai_model"],
                   api_key_env="OPENAI_API_KEY", base_url="https://api.openai.com/v1")
        ds.update(model=values["deepseek_model"])
        credentials = {name: values[field] for field, name in KEY_FIELDS.items() if values[field]}
        input_path, output = resolve_path(values["input"], self.root), resolve_path(values["output"], self.root)
        people, tasks = scoring.prepare_collections(config, input_path, output, providers, dimensions,
                                                    resume=True, check_only=check_only, credentials=credentials)
        return values, config, credentials, people, tasks

    def save(self):
        try:
            values, config, credentials, people, tasks = self.plan(check_only=True)
            save_preferences(self.root, values, self.remember.get())
            self.status.set("Settings saved")
        except Exception as exc:
            self.show_error(exc)

    def check(self):
        try:
            values, config, credentials, people, tasks = self.plan(check_only=True)
            save_preferences(self.root, values, self.remember.get())
            self.status.set(f"Settings valid: {len(people)} CEOs, {len(tasks)} collections, "
                            f"{scoring.target_scores(config['run'])} valid scores per CEO / trait. No API requests made.")
        except Exception as exc:
            self.show_error(exc)

    def start(self):
        if self.busy:
            return
        try:
            values, config, credentials, people, tasks = self.plan()
            save_preferences(self.root, values, self.remember.get())
        except Exception as exc:
            self.show_error(exc)
            return
        self.current_credentials = credentials
        self.stopping.clear()
        self.busy = True
        for widget, state in self.controls:
            widget.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.bar["value"] = 0
        self.status.set("Collecting API ratings...")
        self.tabs.select(self.log_tab)
        self.append_log(f"Starting {config['run']['mode']}: {len(people)} CEOs, {len(tasks)} collections. Saved scores will be reused.")
        export_dir = resolve_path(values["output"], self.root)
        self.thread = threading.Thread(target=self.run_worker, args=(config, credentials, people, tasks, export_dir), daemon=True)
        self.thread.start()

    def run_worker(self, config, credentials, people, tasks, export_dir):
        async def execute():
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.current_task()
            for provider, dimension, settings, folder, metadata in tasks:
                if self.stopping.is_set():
                    raise asyncio.CancelledError()
                factory = lambda p, s, r: scoring.make_api_call(p, s, r, credentials)
                await scoring.run_collection(people, dimension, provider, settings, config["run"], folder,
                                             metadata, True, call_factory=factory,
                                             progress=lambda text: self.events.put(("log", text)),
                                             export_dir=export_dir)
        try:
            asyncio.run(execute())
        except asyncio.CancelledError:
            self.events.put(("done", "Stopped. Saved valid scores will be reused when you start again."))
        except Exception as exc:
            messages = [str(e) if isinstance(e, (ValueError, OSError, ImportError)) else type(e).__name__
                        for e in scoring.error_leaves(exc)]
            self.events.put(("error", "; ".join(messages)))
        else:
            self.events.put(("done", "Complete. Results are ready."))
        finally:
            self.loop = self.task = None

    def stop(self):
        self.stopping.set()
        self.stop_button.configure(state="disabled")
        self.status.set("Stopping and exporting saved scores...")
        loop, task = self.loop, self.task
        if loop is not None and task is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def append_log(self, text):
        for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "AZURE_OPENAI_API_KEY"):
            value = self.current_credentials.get(name, "")
            if len(value) >= 4:
                text = text.replace(value, "[hidden]")
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 2000:
            self.log.delete("1.0", "501.0")
        self.log.see("end")
        self.log.configure(state="disabled")
        match = re.search(r": (\d+)/(\d+) valid scores$", text)
        if match:
            self.bar["value"] = 100 * int(match[1]) / max(1, int(match[2]))
            self.collection_status.set(text)

    def poll(self):
        for _ in range(300):
            try:
                kind, text = self.events.get_nowait()
            except queue.Empty:
                break
            self.append_log(text)
            if kind in ("done", "error"):
                self.busy = False
                self.status.set(text)
                self.stop_button.configure(state="disabled")
                for widget, state in self.controls:
                    widget.configure(state=state)
                self.current_credentials = {}
                if self.closing:
                    self.window.destroy()
                    return
        self.poll_id = self.window.after(100, self.poll)

    def show_error(self, exc):
        messagebox.showerror("Check settings", str(exc), parent=self.window)

    def open_results(self):
        folder = resolve_path(self.fields["output"].get(), self.root)
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])

    def close(self):
        if self.busy:
            self.closing = True
            self.stop()
        else:
            self.window.after_cancel(self.poll_id)
            self.window.destroy()


def main():
    window = tk.Tk()
    try:
        ScoringApp(window)
    except Exception as exc:
        messagebox.showerror("Startup error", str(exc), parent=window)
        window.destroy()
        return 1
    window.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
