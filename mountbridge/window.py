"""Main application window and Gtk.Application entry point."""
import importlib
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from typing import Callable, Dict, Optional, Set

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import Gdk, Gio, GLib, Gtk, Notify

AppIndicator3 = None
for _ns in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(_ns, "0.1")
        AppIndicator3 = importlib.import_module(f"gi.repository.{_ns}")
        break
    except (ValueError, ImportError):
        continue

from .constants import APP_ID, APP_NAME, APP_VERSION, CSS
from .discovery import Discovery
from .models import LiveMount, MountConfig
from .ops import LiveMountScanner, MountOps, mounted_paths
from .parsing import read_mounts, valid_host
from .store import ConfigStore, CredentialError, CredentialStore
from .widgets import (
    DiscoveryPanel,
    MountCard,
    MountDialog,
    SectionRow,
    UnmanagedMountCard,
    default_local_path,
)


def _mount_monitor():
    """GIO's mountinfo watcher: GioUnix.MountMonitor (GLib ≥ 2.80) or Gio.UnixMountMonitor."""
    try:
        gi.require_version("GioUnix", "2.0")
        from gi.repository import GioUnix
        return GioUnix.MountMonitor.get()
    except (ValueError, ImportError, AttributeError):
        pass
    try:
        return Gio.UnixMountMonitor.get()
    except AttributeError:
        return None


def notify(title: str, body: str, ok: bool):
    if not Notify.is_initted():
        return
    icon = "drive-harddisk-symbolic" if ok else "dialog-error-symbolic"
    try:
        Notify.Notification.new(title, body, icon).show()
    except GLib.Error:
        pass  # no notification daemon running


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, cfg: ConfigStore, creds: CredentialStore, ops: MountOps):
        super().__init__(application=app)
        self.cfg = cfg
        self.creds = creds
        self.ops = ops
        self.disc = Discovery()
        self.scanner = LiveMountScanner()
        self.filter_type = "all"
        self._busy: Set[str] = set()                 # mount ids with an operation running
        self._cards: Dict[str, MountCard] = {}
        self._unmanaged_key: tuple = ()
        self._refresh_queued = False

        self._apply_css()
        self._build()
        self._populate()
        self._watch_mounts()
        self._auto_mount()
        if cfg.load_warning:
            GLib.idle_add(self._error_dialog, "Configuration reset", cfg.load_warning)

    # ── CSS ──────────────────────────────────────────────────────────────────

    def _apply_css(self):
        self.get_style_context().add_class("mb-window")
        p = Gtk.CssProvider()
        p.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.set_title(APP_NAME)
        self.set_default_size(920, 600)

    # ── Build ────────────────────────────────────────────────────────────────

    def _build(self):
        # Plain vbox — lets xfwm4 draw native window decorations (no CSD).
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        tb = Gtk.Box(spacing=6)
        tb.get_style_context().add_class("mb-toolbar")
        vbox.pack_start(tb, False, False, 0)

        for icon, tip, cb in (("list-add-symbolic", "Add Mount (Ctrl+N)", self._do_add),
                              ("view-refresh-symbolic", "Refresh Status", self._populate)):
            b = Gtk.Button()
            b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR))
            b.set_tooltip_text(tip)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda *_, cb=cb: cb())
            tb.pack_start(b, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_box.set_valign(Gtk.Align.CENTER)
        title_box.set_hexpand(True)
        title_box.set_halign(Gtk.Align.CENTER)
        tl = Gtk.Label(label=APP_NAME)
        tl.get_style_context().add_class("mb-toolbar-title")
        title_box.pack_start(tl, False, False, 0)
        sub = "Network Mount Manager"
        sl = Gtk.Label(label=f"{sub} · v{APP_VERSION}" if APP_VERSION != "unknown" else sub)
        sl.get_style_context().add_class("mb-toolbar-sub")
        title_box.pack_start(sl, False, False, 0)
        tb.pack_start(title_box, True, True, 0)

        self.search_e = Gtk.SearchEntry()
        self.search_e.set_placeholder_text("Search…")
        self.search_e.set_size_request(180, -1)
        tb.pack_start(self.search_e, False, False, 0)

        root = Gtk.Box()
        root.set_vexpand(True)
        vbox.pack_start(root, True, True, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)

        mp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack.add_named(mp, "mounts")
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        mp.pack_start(scroll, True, True, 0)

        self.lb = Gtk.ListBox()
        self.lb.set_selection_mode(Gtk.SelectionMode.NONE)
        self.lb.set_filter_func(self._filter)
        scroll.add(self.lb)
        self.search_e.connect("search-changed", lambda _: self.lb.invalidate_filter())

        self.status_lbl = Gtk.Label(label="", xalign=0)
        self.status_lbl.get_style_context().add_class("mb-statusbar")
        mp.pack_start(self.status_lbl, False, False, 0)

        self.stack.add_named(DiscoveryPanel(self.disc, self._add_discovered), "discovery")

        # Sidebar last: its row-selected handler touches self.lb / self.stack.
        root.pack_start(self._build_sidebar(), False, True, 0)
        root.pack_start(self.stack, True, True, 0)

        vbox.show_all()
        self.stack.set_visible_child_name("mounts")
        self.nav_lb.select_row(self._nav_rows[0])

    def _build_sidebar(self):
        sb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sb.get_style_context().add_class("mb-sidebar")

        def section(text):
            lbl = Gtk.Label(label=text, xalign=0)
            lbl.get_style_context().add_class("mb-section-label")
            sb.pack_start(lbl, False, False, 0)

        def nav_row(icon, label):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=10)
            box.get_style_context().add_class("mb-nav-row")
            row.add(box)
            box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR),
                           False, False, 0)
            lw = Gtk.Label(label=label, xalign=0)
            lw.set_hexpand(True)
            box.pack_start(lw, True, True, 0)
            return row, box

        section("MOUNTS")
        self.nav_lb = Gtk.ListBox()
        self.nav_lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_lb.connect("row-selected", self._nav_selected)
        sb.pack_start(self.nav_lb, False, False, 0)

        self._nav_rows = []
        for icon, label, key in [
            ("drive-harddisk-symbolic",     "All Mounts", "all"),
            ("network-server-symbolic",     "NFS",        "nfs"),
            ("network-workgroup-symbolic",  "SMB / CIFS", "smb"),
            ("utilities-terminal-symbolic", "SSHFS",      "sshfs"),
        ]:
            row, box = nav_row(icon, label)
            row._key = key
            cl = Gtk.Label(label="0")
            cl.get_style_context().add_class("mb-badge")
            box.pack_start(cl, False, False, 0)
            row._count = cl
            self.nav_lb.add(row)
            self._nav_rows.append(row)

        sep = Gtk.Separator()
        sep.set_margin_top(10)
        sep.set_margin_bottom(4)
        sb.pack_start(sep, False, False, 0)

        section("TOOLS")
        self.tools_lb = Gtk.ListBox()
        self.tools_lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.tools_lb.connect("row-selected", self._tools_selected)
        sb.pack_start(self.tools_lb, False, False, 0)
        drow, _ = nav_row("network-wireless-symbolic", "Discover")
        self.tools_lb.add(drow)

        sb.show_all()
        return sb

    # ── Sidebar ──────────────────────────────────────────────────────────────

    def _nav_selected(self, _lb, row):
        if row:
            self.tools_lb.unselect_all()
            self.filter_type = row._key
            self.lb.invalidate_filter()
            self.stack.set_visible_child_name("mounts")

    def _tools_selected(self, _lb, row):
        if row:
            self.nav_lb.unselect_all()
            self.stack.set_visible_child_name("discovery")

    def _show_mounts(self):
        self.nav_lb.select_row(self._nav_rows[0])

    # ── Filter ───────────────────────────────────────────────────────────────

    def _filter(self, row):
        if isinstance(row, UnmanagedMountCard):
            mtype, fields = row.lm.mount_type, (row.lm.host, row.lm.remote_path, row.lm.local_path)
        elif isinstance(row, MountCard):
            m = row.mount
            mtype, fields = m.mount_type, (m.name, m.host, m.remote_path)
        else:
            return True
        if self.filter_type != "all" and mtype != self.filter_type:
            return False
        q = self.search_e.get_text().lower()
        return not q or any(q in f.lower() for f in fields)

    # ── Populate / refresh ───────────────────────────────────────────────────

    def _known_paths(self) -> Set[str]:
        return {self.ops.mountpoint(m) for m in self.cfg.mounts}

    def _populate(self):
        """Rebuild the list. Only on config changes or when unmanaged mounts come and go."""
        for c in self.lb.get_children():
            self.lb.remove(c)
        self._cards.clear()

        entries = read_mounts()
        mounted = mounted_paths(entries)
        for m in self.cfg.mounts:
            card = MountCard(m, self._toggle, self._open, self._do_edit, self._do_delete)
            card.update(self.ops.is_mounted(m, mounted), m.id in self._busy)
            self._cards[m.id] = card
            self.lb.add(card)

        unmanaged = self.scanner.scan(self._known_paths(), entries)
        self._unmanaged_key = tuple(sorted(lm.local_path for lm in unmanaged))
        if unmanaged:
            self.lb.add(SectionRow("UNMANAGED LIVE MOUNTS"))
            for lm in unmanaged:
                self.lb.add(UnmanagedMountCard(lm, self._import_live, self._open_path,
                                               self._unmount_live))
        if not self.cfg.mounts and not unmanaged:
            self._empty_state()

        self.lb.show_all()
        self._update_counts(mounted, unmanaged)

    def _refresh(self):
        """Cheap status update: reads mountinfo once, updates cards in place."""
        self._refresh_queued = False
        entries = read_mounts()
        mounted = mounted_paths(entries)
        unmanaged = self.scanner.scan(self._known_paths(), entries)
        if tuple(sorted(lm.local_path for lm in unmanaged)) != self._unmanaged_key:
            self._populate()
            return False
        for m in self.cfg.mounts:
            card = self._cards.get(m.id)
            if card:
                card.update(self.ops.is_mounted(m, mounted), m.id in self._busy)
        self._update_counts(mounted, unmanaged)
        return False

    def _queue_refresh(self, *_):
        if not self._refresh_queued:
            self._refresh_queued = True
            GLib.idle_add(self._refresh)

    def _watch_mounts(self):
        self._monitor = _mount_monitor()
        if self._monitor:
            self._monitor.connect("mounts-changed", self._queue_refresh)
        # Safety net (and the only mechanism if no monitor is available).
        GLib.timeout_add_seconds(30 if self._monitor else 5,
                                 lambda: self._queue_refresh() or True)

    def _empty_state(self):
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.get_style_context().add_class("mb-empty")
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        row.add(box)

        icon = Gtk.Image.new_from_icon_name("network-server-symbolic", Gtk.IconSize.DIALOG)
        icon.get_style_context().add_class("mb-empty-icon")
        icon.set_pixel_size(80)
        box.pack_start(icon, False, False, 0)
        t = Gtk.Label(label="No mounts configured yet")
        t.get_style_context().add_class("mb-empty-title")
        box.pack_start(t, False, False, 0)
        s = Gtk.Label(label="Add an NFS export, SMB share, or SSHFS connection\nto get started.",
                      justify=Gtk.Justification.CENTER)
        s.get_style_context().add_class("mb-empty-sub")
        box.pack_start(s, False, False, 0)
        btn = Gtk.Button(label="  + Add Your First Mount  ")
        btn.get_style_context().add_class("suggested-action")
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda _: self._do_add())
        box.pack_start(btn, False, False, 0)
        self.lb.add(row)

    def _update_counts(self, mounted: Set[str], unmanaged: list):
        counts = {"all": 0, "nfs": 0, "smb": 0, "sshfs": 0}
        active = 0
        for m in self.cfg.mounts:
            counts["all"] += 1
            counts[m.mount_type] = counts.get(m.mount_type, 0) + 1
            active += self.ops.is_mounted(m, mounted)
        for lm in unmanaged:
            counts["all"] += 1
            counts[lm.mount_type] = counts.get(lm.mount_type, 0) + 1
            active += 1
        for row in self._nav_rows:
            row._count.set_text(str(counts.get(row._key, 0)))
        total = counts["all"]
        self.status_lbl.set_text(
            f"  {active} of {total} mount{'s' if total != 1 else ''} active"
            + (f"  •  {len(unmanaged)} unmanaged" if unmanaged else "")
        )

    # ── Mount operations (all run off the main thread) ───────────────────────

    def _run_op(self, m: MountConfig, action: str, lazy: bool = False,
                then: Optional[Callable[[bool], None]] = None, notify_ok: bool = True):
        if m.id in self._busy:
            return
        self._busy.add(m.id)
        card = self._cards.get(m.id)
        if card:
            card.update(self.ops.is_mounted(m), busy=True)

        def work():
            if action == "mount":
                ok, msg = self.ops.mount(m)
            else:
                ok, msg = self.ops.unmount(m, lazy=lazy)
            GLib.idle_add(self._op_done, m, action, lazy, ok, msg, then, notify_ok)

        threading.Thread(target=work, daemon=True).start()

    def _op_done(self, m, action, lazy, ok, msg, then, notify_ok):
        self._busy.discard(m.id)
        self._queue_refresh()
        if not ok and action == "unmount" and not lazy and "busy" in msg.lower():
            if self._confirm(f'"{m.name}" is busy',
                             "Files on it are still open. Detach it now anyway (lazy unmount)? "
                             "It will finish unmounting once the files are closed."):
                self._run_op(m, "unmount", lazy=True, then=then, notify_ok=notify_ok)
                return False
        if not ok or notify_ok:
            verb = "Mounted" if action == "mount" else "Unmounted"
            notify(m.name, verb if ok and msg == "OK" else msg, ok)
        if not ok:
            self.status_lbl.set_text(f"  {m.name}: {msg.splitlines()[0] if msg else 'failed'}")
        if then:
            then(ok)
        return False

    def _toggle(self, m: MountConfig):
        self._run_op(m, "unmount" if self.ops.is_mounted(m) else "mount")

    def _open(self, m: MountConfig):
        link, real = os.path.expanduser(m.local_path), self.ops.mountpoint(m)
        self._open_path(link if os.path.realpath(link) == real else real)

    def _open_path(self, path: str):
        """Open a folder in the file manager, reporting unreachable mounts instead of
        failing silently. The accessibility check runs off the main thread because
        stat() on a dead network mount can block."""
        state = {"done": False}

        def check():
            try:
                os.listdir(path)
                err = None
            except OSError as e:
                err = e.strerror or str(e)
            GLib.idle_add(finish, err)

        def finish(err):
            if state["done"]:
                return False
            state["done"] = True
            if err:
                self._error_dialog(f"Can't open {path}",
                                   f"{err}.\n\nThe server may be offline or unreachable. "
                                   "Unmount it and mount again once the server is back.")
                return False
            try:
                subprocess.Popen(["xdg-open", path], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                self._error_dialog("Can't open folder", f"xdg-open failed: {e}")
            return False

        threading.Thread(target=check, daemon=True).start()
        GLib.timeout_add_seconds(5, lambda: finish("Not responding after 5 seconds"))

    def _unmount_live(self, card: UnmanagedMountCard):
        card.set_busy(True)

        def work():
            ok, msg = self.ops.unmount_live(card.lm)
            GLib.idle_add(done, ok, msg)

        def done(ok, msg):
            notify(card.lm.host, "Unmounted" if ok else msg, ok)
            if not ok:
                self._error_dialog("Unmount failed", msg)
            self._populate()
            return False

        threading.Thread(target=work, daemon=True).start()

    def _auto_mount(self):
        pending = [m for m in self.cfg.mounts if m.auto_mount and not self.ops.is_mounted(m)]
        if not pending:
            return
        net = Gio.NetworkMonitor.get_default()

        def go():
            for m in pending:
                self._run_op(m, "mount", notify_ok=False)

        if net.get_network_available():
            go()
            return

        def changed(mon, available):
            if available:
                mon.disconnect(handler)
                go()

        handler = net.connect("network-changed", changed)

    # ── Dialog helpers ───────────────────────────────────────────────────────

    def _run_dialog(self, d: MountDialog) -> Optional[dict]:
        """Keep the dialog open until the input validates or the user cancels."""
        try:
            while d.run() == Gtk.ResponseType.OK:
                err = d.validate()
                if not err:
                    return d.values()
                d.show_error(err)
            return None
        finally:
            d.destroy()

    def _confirm(self, title: str, body: str) -> bool:
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.YES_NO, text=title)
        dlg.format_secondary_text(body)
        try:
            return dlg.run() == Gtk.ResponseType.YES
        finally:
            dlg.destroy()

    def _error_dialog(self, title: str, body: str):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.CLOSE, text=title)
        dlg.format_secondary_text(body)
        dlg.run()
        dlg.destroy()
        return False

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def _make_config(self, v: dict, fallback_path: str = "") -> MountConfig:
        taken = {os.path.expanduser(m.local_path) for m in self.cfg.mounts}
        return MountConfig(
            id=uuid.uuid4().hex[:8],
            name=v["name"],
            mount_type=v["mount_type"],
            host=v["host"],
            remote_path=v["remote_path"],
            local_path=v["local_path"] or fallback_path or default_local_path(v["name"], taken),
            username=v["username"],
            domain=v["domain"],
            port=v["port"],
            ssh_key=v["ssh_key"],
            options=v["options"],
            auto_mount=v["auto_mount"],
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

    def _store_password(self, m: MountConfig, password: str):
        try:
            self.creds.store(m.id, password)
        except CredentialError as e:
            self._error_dialog("Password not saved",
                               f"{e}\n\n\"{m.name}\" was saved without its password, so mounting it "
                               "will fail until a keyring (e.g. gnome-keyring) is running. "
                               "Then edit the mount and enter the password again.")

    def _save_new(self, v: dict, fallback_path: str = ""):
        m = self._make_config(v, fallback_path)
        self.cfg.add(m)
        self._populate()
        if v["password"]:
            self._store_password(m, v["password"])

    def _do_add(self):
        v = self._run_dialog(MountDialog(self))
        if v:
            self._save_new(v)

    def _add_discovered(self, host, path, mtype):
        if not valid_host(host):
            self._error_dialog("Invalid host", f"Discovery returned an invalid hostname: {host!r}")
            return
        prefill = MountConfig(id="", name=f"{host} {path or ''}".strip(), mount_type=mtype,
                              host=host, remote_path=path or "", local_path="")
        v = self._run_dialog(MountDialog(self, prefill=prefill))
        if v:
            self._save_new(v)
            self._show_mounts()

    def _import_live(self, lm: LiveMount):
        """Open the add dialog pre-filled from a live unmanaged mount."""
        prefill = MountConfig(id="", name=f"{lm.host} {lm.remote_path}", mount_type=lm.mount_type,
                              host=lm.host, remote_path=lm.remote_path, local_path=lm.local_path,
                              username=lm.username, port=lm.port)
        v = self._run_dialog(MountDialog(self, prefill=prefill))
        if v:
            self._save_new(v, fallback_path=lm.local_path)

    def _do_edit(self, mount: MountConfig):
        if mount.id in self._busy or self.ops.is_mounted(mount):
            self._error_dialog("Unmount first",
                               f'Unmount "{mount.name}" before editing its settings.')
            return
        v = self._run_dialog(MountDialog(self, mount=mount))
        if not v:
            return
        for k in ("name", "mount_type", "host", "remote_path", "username", "domain",
                  "port", "ssh_key", "options", "auto_mount"):
            setattr(mount, k, v[k])
        mount.local_path = v["local_path"] or mount.local_path
        self.cfg.update(mount)
        self._populate()
        if v["clear_password"]:
            self.creds.delete(mount.id)
        elif v["password"]:
            self._store_password(mount, v["password"])

    def _do_delete(self, mount: MountConfig):
        if mount.id in self._busy:
            return
        if not self._confirm(f'Remove "{mount.name}"?',
                             "It will be unmounted, and its configuration and stored "
                             "password deleted. Data on the server is not affected."):
            return

        def finish(ok: bool):
            if not ok:
                self._error_dialog("Not removed",
                                   f'"{mount.name}" could not be unmounted, so it was kept.')
                return
            self.creds.delete(mount.id)
            self.cfg.delete(mount.id)
            self._populate()

        if self.ops.is_mounted(mount):
            self._run_op(mount, "unmount", then=finish, notify_ok=False)
        else:
            finish(True)


# ── Application ──────────────────────────────────────────────────────────────

class MountBridgeApp(Gtk.Application):
    def __init__(self, start_hidden: bool = False):
        super().__init__(application_id=APP_ID)
        self.start_hidden = start_hidden
        self.cfg: Optional[ConfigStore] = None
        self.win: Optional[MainWindow] = None
        self._tray_ref = None
        self._tray_menu = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Notify.init(APP_NAME)
        self.cfg = ConfigStore()
        self.creds = CredentialStore()
        self.ops = MountOps(self.creds)
        for name, accel, cb in (("add-mount", "<Primary>n", lambda *_: self._add_mount()),
                                ("quit", "<Primary>q", lambda *_: self.quit())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
            self.set_accels_for_action(f"app.{name}", [accel])

    def _add_mount(self):
        self.win.present()
        self.win._do_add()

    def do_activate(self):
        first = self.win is None
        if first:
            self.win = MainWindow(self, self.cfg, self.creds, self.ops)
            if self._tray():
                self.hold()  # keep running in the tray when the window is closed
                self.win.connect("delete-event", lambda w, _e: w.hide_on_delete())
        if not (first and self.start_hidden and self._tray_ref):
            self.win.present()

    def _menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        for label, cb in ((f"Open {APP_NAME}", lambda _: self.win.present()),
                          (None, None), ("Quit", lambda _: self.quit())):
            item = Gtk.SeparatorMenuItem() if label is None else Gtk.MenuItem(label=label)
            if cb:
                item.connect("activate", cb)
            menu.append(item)
        menu.show_all()
        self._tray_menu = menu  # keep a Python reference alive
        return menu

    def _tray(self) -> bool:
        """Create a tray icon. References are kept on self so they aren't garbage-collected."""
        if AppIndicator3 is not None:
            try:
                ind = AppIndicator3.Indicator.new(
                    APP_ID, "drive-harddisk-symbolic",
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
                ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
                ind.set_menu(self._menu())
                self._tray_ref = ind
                return True
            except Exception as e:
                print(f"[tray] AppIndicator failed: {e}", file=sys.stderr)
        try:
            si = Gtk.StatusIcon.new_from_icon_name("drive-harddisk-symbolic")
            si.set_tooltip_text(APP_NAME)
            si.connect("activate", lambda _: self.win.present())
            menu = self._menu()
            si.connect("popup-menu", lambda _i, btn, t: menu.popup(None, None, None, None, btn, t))
            self._tray_ref = si
            return True
        except Exception as e:
            print(f"[tray] StatusIcon failed: {e}", file=sys.stderr)
            return False


def main():
    argv = [a for a in sys.argv if a != "--hidden"]
    app = MountBridgeApp(start_hidden=len(argv) != len(sys.argv))
    sys.exit(app.run(argv))
