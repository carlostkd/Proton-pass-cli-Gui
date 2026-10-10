import os
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "Proton Pass CLI GUI"
SUBPROCESS_TIMEOUT = 60

def run_cli(args, env=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            ["pass-cli"] + [a for a in args if a != ""],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT, env=merged
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 1, "", "pass-cli not found in PATH"
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"

def get_vaults():
    code, out, _ = run_cli(["vault", "list"])
    vaults = []
    if code == 0:
        for line in out.splitlines():
            if "]:" in line:
                vaults.append(line.split("]:", 1)[1].strip())
    return vaults

def get_share_id(vault):
    code, out, _ = run_cli(["vault", "list"])
    if code == 0:
        for line in out.splitlines():
            if line.endswith("]: " + vault):
                return line[line.find("[") + 1:line.find("]")]
    return None

def get_items(vault):
    code, out, _ = run_cli(["item", "list", "--vault-name", vault])
    items = []
    if code == 0:
        for line in out.splitlines():
            if "]:" in line:
                item_id = line[line.find("[") + 1:line.find("]")]
                title = line.split("]:", 1)[1].split("(state=")[0].strip()
                items.append((title, item_id))
    return items

def get_fields(vault, item_title):
    share_id = get_share_id(vault)
    item_id = None
    for t, iid in get_items(vault):
        if t == item_title:
            item_id = iid
            break
    if not share_id or not item_id:
        return []
    code, out, _ = run_cli(
        ["item", "view", f"pass://{share_id}/{item_id}", "--output", "json"],
        env={"PROTON_PASS_AGENT_REASON": "GUI field discovery"})
    fields = ["Title", "note", "username", "password"]
    if code == 0 and out:
        for name in re.findall(r'"name":\s*"([^"]+)"', out):
            if name not in fields:
                fields.append(name)
    return fields

ARG_VAULT = "vault"
ARG_ITEM = "item"
ARG_FIELD = "field"
ARG_TEXT = "text"
ARG_FILE_IN = "file_in"
ARG_FILE_OUT = "file_out"
ARG_PASS = "password"
ARG_MULTI = "multi"

COMMANDS = [
    ("Session", [
        ("Login (Web)", [], ["login"]),
        ("Login (PAT)", [("Personal Access Token", ARG_PASS, False)],
         ["login"], "PROTON_PASS_PERSONAL_ACCESS_TOKEN"),
        ("Logout", [], ["logout"]),
        ("Info", [], ["info"]),
    ]),
    ("Browse", [
        ("Vault List", [], ["vault", "list"]),
        ("Share List", [], ["share", "list"]),
        ("Item List (vault)", [("Vault", ARG_VAULT, True)],
         ["item", "list", "--vault-name", "{Vault}"]),
        ("Item View (vault/item)", [("Vault", ARG_VAULT, True), ("Item", ARG_ITEM, True)],
         ["item", "view", "--vault-name", "{Vault}", "--item-title", "{Item}"],
         "PROTON_PASS_AGENT_REASON"),
        ("Item View (JSON)", [("Vault", ARG_VAULT, True), ("Item", ARG_ITEM, True)],
         ["item", "view", "--vault-name", "{Vault}", "--item-title", "{Item}",
          "--output", "json"], "PROTON_PASS_AGENT_REASON"),
        ("Agent Instructions", [], ["agent", "instructions"]),
    ]),
    ("Secrets", [
        ("Inject", [("Vault", ARG_VAULT, True), ("Item", ARG_ITEM, True),
                    ("Field", ARG_FIELD, True),
                    ("Key Name (optional, used if template has no placeholder)",
                     ARG_TEXT, False),
                    ("Source Template", ARG_FILE_IN, True),
                    ("Destination File", ARG_FILE_OUT, True)], ["__INJECT__"]),
    ]),
    ("Vault Ops", [
        ("Vault Create", [("Vault Name", ARG_TEXT, True)],
         ["vault", "create", "--name", "{Vault Name}"]),
        ("Vault Rename", [("Vault", ARG_VAULT, True), ("New Name", ARG_TEXT, True)],
         ["vault", "update", "--vault-name", "{Vault}", "--name", "{New Name}"]),
        ("Vault Delete", [("Vault", ARG_VAULT, True)],
         ["vault", "delete", "--vault-name", "{Vault}"]),
    ]),
    ("Item Ops", [
        ("Item Create Login", [("Vault", ARG_VAULT, True), ("Title", ARG_TEXT, True)],
         ["item", "create", "login", "--vault-name", "{Vault}", "--title", "{Title}"]),
        ("Item Create Note", [("Vault", ARG_VAULT, True), ("Title", ARG_TEXT, True),
                              ("Note Body", ARG_MULTI, True)],
         ["item", "create", "note", "--vault-name", "{Vault}", "--title", "{Title}",
          "--note", "{Note Body}"]),
        ("Item Trash", [("Vault", ARG_VAULT, True), ("Item", ARG_ITEM, True)],
         ["item", "trash", "--vault-name", "{Vault}", "--item-title", "{Item}"]),
        ("Item Untrash", [("Vault", ARG_VAULT, True), ("Item", ARG_ITEM, True)],
         ["item", "untrash", "--vault-name", "{Vault}", "--item-title", "{Item}"]),
    ]),
    ("Advanced", [
        ("Custom Command", [("Arguments (space separated)", ARG_TEXT, True)],
         ["__CUSTOM__"]),
    ]),
]

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1100x760")
        self.minsize(900, 600)
        self.selected_cmd = None
        self.current_args = []

        style = ttk.Style(self)
        style.configure("Pass.Treeview", rowheight=34, font=("", 10))
        style.configure("TFrame", background="#1e1e1e")
        style.configure("TLabelFrame", background="#252526", foreground="#cccccc")
        style.configure("TLabelFrame.Label", background="#252526", foreground="#9cdcfe")
        style.configure(" TLabel", background="#1e1e1e", foreground="#d4d4d4")
        style.configure("TButton", background="#3c3c3c", foreground="#ffffff")
        style.map("TButton", background=[("active", "#007acc"), ("pressed", "#005a9e")])
        style.configure("Combobox", fieldbackground="#3c3c3c", foreground="#d4d4d4")
        style.map("Combobox", fieldbackground=[("readonly", "#3c3c3c")])

        style.configure("Treeview", background="#2d2d30", foreground="#d4d4d4", fieldbackground="#2d2d30", rowheight=25)
        style.map("Treeview", background=[("selected", "#094771"), ("focus", "#094771")])
        style.configure("Treeview.Heading", background="#2d2d30", foreground="#cccccc", font=("", 9, "bold"))

        main = ttk.Frame(self, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, width=280)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8), pady=2)
        left.pack_propagate(False)

        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.cmd_list = ttk.Treeview(left, show="tree", selectmode="browse",
                                      style="Pass.Treeview")
        self.cmd_list.pack(fill=tk.BOTH, expand=True)
        self.cmd_list.bind("<<TreeviewSelect>>", self.on_command_selected)

        form_wrap = ttk.LabelFrame(right, text="Command Builder", padding=8)
        form_wrap.pack(fill=tk.X, pady=4)
        self.form_frame = ttk.Frame(form_wrap)
        self.form_frame.pack(fill=tk.X)

        run_btn = ttk.Button(right, text="Execute", command=self.execute_thread)
        run_btn.pack(pady=6, anchor=tk.W)

        out_wrap = ttk.LabelFrame(right, text="Output (selectable, Ctrl+C to copy)", padding=8)
        out_wrap.pack(fill=tk.BOTH, expand=True)

        self.output = tk.Text(out_wrap, wrap=tk.NONE, font=("Monospace", 10),
                              bg="#1e1e1e", fg="#d4d4d4", insertbackground="#ffffff")
        yscroll = ttk.Scrollbar(out_wrap, orient=tk.VERTICAL, command=self.output.yview)
        xscroll = ttk.Scrollbar(out_wrap, orient=tk.HORIZONTAL, command=self.output.xview)
        self.output.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.output.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        out_wrap.rowconfigure(0, weight=1)
        out_wrap.columnconfigure(0, weight=1)
        self.output.tag_configure("ok", foreground="#4db6ac", background="#002b36")
        self.output.tag_configure("err", foreground="#f48fb1", background="#2a0015")
        self.output.tag_configure("info", foreground="#9cdcfe")
        self.output.bind("<Key>", self.readonly_keys)
        self.output.bind("<Button-3>", self.output_context_menu)

        self.populate_commands()
        self.after(100, self.warmup)

    def readonly_keys(self, event):
        if event.state & 0x0004 and event.keysym.lower() in ("c", "a"):
            return None
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End",
                            "Prior", "Next", "Shift_L", "Shift_R"):
            return None
        return "break"

    def output_context_menu(self, event):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Copy", command=self.copy_selection)
        menu.add_command(label="Select All", command=self.select_all_output)
        menu.tk_popup(event.x_root, event.y_root)

    def copy_selection(self):
        try:
            text = self.output.get("sel.first", "sel.last")
            self.clipboard_clear()
            self.clipboard_append(text)
        except tk.TclError:
            pass

    def select_all_output(self):
        self.output.tag_add("sel", "1.0", "end")
        self.output.mark_set("insert", "1.0")

    def warmup(self):
        code, out, err = run_cli(["info"])
        if code == 0:
            self.append_output("Session active:\n" + out + "\n", "ok")
        else:
            self.append_output("No active session. Use Login under Session.\n" + err + "\n", "err")

    def populate_commands(self):
        self.tree_map = {}
        for entry in COMMANDS:
            category, cmds = entry[0], entry[1]
            node = self.cmd_list.insert("", tk.END, text=category, open=True)
            for cmd_def in cmds:
                label, args, template = cmd_def[0], cmd_def[1], cmd_def[2]
                env_key = cmd_def[3] if len(cmd_def) > 3 else None
                leaf = self.cmd_list.insert(node, tk.END, text=label)
                self.tree_map[leaf] = (label, args, template, env_key)

    def on_command_selected(self, event):
        sel = self.cmd_list.selection()
        if not sel or sel[0] not in self.tree_map:
            return
        for widget in self.form_frame.winfo_children():
            widget.destroy()
        label, args, template, env_key = self.tree_map[sel[0]]
        self.selected_cmd = (label, args, template, env_key)
        self.current_args = []
        cmd_label = ttk.Label(self.form_frame, text="Selected: " + label,
                  font=("", 10, "bold"))
        cmd_label.configure(foreground="#4fc3f7")
        cmd_label.grid(row=0, column=0, columnspan=3,
                      sticky=tk.W, pady=(0, 6))

        row = 1
        for arg_label, arg_type, required in args:
            ttk.Label(self.form_frame, text=arg_label).grid(
                row=row, column=0, sticky=tk.NW, padx=(0, 6), pady=2)

            if arg_type == ARG_VAULT:
                var = ttk.Combobox(self.form_frame, state="readonly")
                var.grid(row=row, column=1, sticky=tk.EW, pady=2)
                btn = ttk.Button(self.form_frame, text="Load Vaults",
                           command=lambda v=var: self.refresh_vault_combo(v))
                btn.grid(row=row, column=2, padx=4)
            elif arg_type == ARG_ITEM:
                var = ttk.Combobox(self.form_frame, state="readonly")
                var.grid(row=row, column=1, sticky=tk.EW, pady=2)
                btn = ttk.Button(self.form_frame, text="Load Items",
                           command=lambda v=var: self.refresh_items_combo(v))
                btn.grid(row=row, column=2, padx=4)
            elif arg_type == ARG_FIELD:
                var = ttk.Combobox(self.form_frame, state="readonly")
                var.grid(row=row, column=1, sticky=tk.EW, pady=2)
                btn = ttk.Button(self.form_frame, text="Load Fields",
                           command=lambda v=var: self.refresh_fields_combo(v))
                btn.grid(row=row, column=2, padx=4)
            elif arg_type == ARG_FILE_IN:
                var = self.file_row(row, save=False)
            elif arg_type == ARG_FILE_OUT:
                var = self.file_row(row, save=True)
            elif arg_type == ARG_PASS:
                var = ttk.Entry(self.form_frame, show="*")
                var.grid(row=row, column=1, sticky=tk.EW, pady=2)
            elif arg_type == ARG_MULTI:
                var = tk.Text(self.form_frame, height=4, font=("Monospace", 10),
                              bg="#3c3c3c", fg="#d4d4d4", insertbackground="#ffffff")
                var.grid(row=row, column=1, sticky=tk.EW, pady=2)
            else:
                var = ttk.Entry(self.form_frame)
                var.grid(row=row, column=1, sticky=tk.EW, pady=2)

            self.form_frame.columnconfigure(1, weight=1)
            self.current_args.append((arg_label, arg_type, var, required))
            row += 1

    def file_row(self, row, save):
        holder = {"path": tk.StringVar()}
        entry = ttk.Entry(self.form_frame, textvariable=holder["path"])
        entry.grid(row=row, column=1, sticky=tk.EW, pady=2)

        def browse():
            if save:
                path = filedialog.asksaveasfilename()
            else:
                path = filedialog.askopenfilename()
            if path:
                holder["path"].set(path)

        btn = ttk.Button(self.form_frame, text="Browse", command=browse)
        btn.grid(row=row, column=2, padx=4)
        return entry

    def get_selected_vault(self):
        for _, arg_type, var, _ in self.current_args:
            if arg_type == ARG_VAULT:
                return var.get()
        return None

    def get_selected_item(self):
        for label, arg_type, var, _ in self.current_args:
            if arg_type == ARG_ITEM:
                idx = var.current()
                if idx >= 0 and hasattr(var, "items_data") and var.items_data:
                    return var.items_data[idx][0]
                return var.get()
        return None

    def refresh_vault_combo(self, box):
        vaults = get_vaults()
        box.configure(values=vaults)
        if vaults and not box.get():
            box.set(vaults[0])

    def refresh_items_combo(self, box):
        vault = self.get_selected_vault()
        if not vault:
            messagebox.showwarning("Missing vault", "Load and select a vault first.")
            return
        items = get_items(vault)
        box.configure(values=[f"{title}  ({item_id[:12]}...)" for title, item_id in items])
        box.items_data = items

    def refresh_fields_combo(self, box):
        vault = self.get_selected_vault()
        item = self.get_selected_item()
        if not vault or not item:
            messagebox.showwarning("Missing selection", "Load and select a vault and item first.")
            return
        fields = get_fields(vault, item)
        if not fields:
            messagebox.showwarning("No fields", "Could not discover fields for this item.")
            return
        box.configure(values=fields)
        box.set(fields[0])

    def collect_values(self):
        vals = {}
        for label, arg_type, var, required in self.current_args:
            if arg_type == ARG_MULTI:
                value = var.get("1.0", tk.END).strip()
            elif arg_type == ARG_FILE_IN or arg_type == ARG_FILE_OUT:
                value = var.get()
            else:
                value = var.get().strip()
            if arg_type == ARG_ITEM and value:
                idx = var.current()
                if idx >= 0 and hasattr(var, "items_data") and var.items_data:
                    value = var.items_data[idx][0]
            if required and not value:
                raise ValueError("Missing required value: " + label)
            vals[label] = value
        return vals

    def execute_thread(self):
        if not self.selected_cmd:
            return
        label, args, template, env_key = self.selected_cmd
        try:
            vals = self.collect_values()
        except ValueError as e:
            self.append_output(str(e) + "\n", "err")
            return
        token_value = vals.get("Personal Access Token", "")
        threading.Thread(
            target=self.execute,
            args=(label, template, env_key, vals, token_value),
            daemon=True
        ).start()

    def execute(self, label, template, env_key, vals, token_value):
        self.append_output("$ " + label + "\n", "info")

        if template[0] == "__INJECT__":
            self.do_inject(vals)
            return
        if template[0] == "__CUSTOM__":
            custom_args = vals.get("Arguments (space separated)", "").split()
            code, out, err = run_cli(custom_args)
            self.report(code, out, err)
            return

        final_args = [vals.get(part.strip("{}"), part) if part.startswith("{")
                      else part for part in template]
        final_args = [a for a in final_args if a != ""]

        env = {}
        if env_key == "PROTON_PASS_AGENT_REASON":
            env["PROTON_PASS_AGENT_REASON"] = "GUI interaction by vault owner"
        elif env_key == "PROTON_PASS_PERSONAL_ACCESS_TOKEN" and token_value:
            env["PROTON_PASS_PERSONAL_ACCESS_TOKEN"] = token_value

        code, out, err = run_cli(final_args, env if env else None)
        self.report(code, out, err)

    def report(self, code, out, err):
        tag = "ok" if code == 0 else "err"
        if out:
            self.append_output(out + "\n", tag)
        if err:
            self.append_output(err + "\n", tag)

    def build_reference(self, vals):
        vault = vals.get("Vault", "")
        item_title = vals.get("Item", "")
        share_id = get_share_id(vault)
        item_id = None
        for t, iid in get_items(vault):
            if t == item_title:
                item_id = iid
                break
        if not share_id or not item_id:
            return None
        return f"pass://{share_id}/{item_id}"

    def do_inject(self, vals):
        src = vals.get("Source Template", "")
        dst = vals.get("Destination File", "")
        field = vals.get("Field", "")
        key_name = vals.get(
            "Key Name (optional, used if template has no placeholder)", "")
        if not src or not dst:
            self.append_output("Source and destination required.\n", "err")
            return
        if not os.path.isfile(src):
            self.append_output("Source file not found: " + src + "\n", "err")
            return

        ref = self.build_reference(vals)
        if not ref:
            self.append_output("Could not resolve vault/item to a reference.\n", "err")
            return
        full_ref = ref + "/" + field

        try:
            with open(src, "r") as fh:
                content = fh.read()
        except OSError as e:
            self.append_output("Cannot read template: " + str(e) + "\n", "err")
            return

        if key_name:
            cleaned = re.sub(r"[ \t]*\{\{\s*pass://[^\s}]+\s*\}\}[ \t]*", "", content)
            cleaned = re.sub(r"^[ \t]*\n", "", cleaned, flags=re.MULTILINE)
            if cleaned and not cleaned.endswith("\n"):
                cleaned += "\n"
            entry = key_name + "={{ " + full_ref + " }}"
            new_content = cleaned + entry + "\n"
            self.append_output("Using key name: " + key_name + "\n", "ok")
        else:
            has_placeholder = re.search(r"\{\{\s*pass://", content)
            if not has_placeholder:
                entry = field + "={{ " + full_ref + " }}"
                if content and not content.endswith("\n"):
                    content += "\n"
                new_content = content + entry + "\n"
                self.append_output(
                    "No placeholder and no key name given, added: " + entry + "\n", "ok")
            else:
                new_content = content

        try:
            with open(src, "w") as fh:
                fh.write(new_content)
        except OSError as e:
            self.append_output("Cannot write template: " + str(e) + "\n", "err")
            return

        code, out, err = run_cli(
            ["inject", "--in-file", src, "--out-file", dst, "--force"])
        self.report(code, out, err)

        if code == 0 and os.path.isfile(dst):
            self.append_output("Contents of " + dst + ":\n", "ok")
            try:
                with open(dst, "r") as fh:
                    self.append_output(fh.read() + "\n", "ok")
            except OSError:
                pass

    def append_output(self, text, tag=None):
        self.after(0, lambda: self._append(text, tag))

    def _append(self, text, tag):
        self.output.insert(tk.END, text, tag if tag else "")
        self.output.see(tk.END)

if __name__ == "__main__":
    app = App()
    app.mainloop()
