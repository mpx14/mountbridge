"""Main application window and Gtk.Application entry point."""
import os
import sys
import threading
import uuid
from datetime import datetime

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, GLib, Gdk, Notify

HAS_INDICATOR = False
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
    HAS_INDICATOR = True
except Exception:
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3
        HAS_INDICATOR = True
    except Exception:
        pass

from .constants import APP_ID, APP_NAME, APP_VERSION, CSS, MOUNTS_DIR
from .models import MountConfig, LiveMount
from .store import ConfigStore, CredentialStore
from .ops import MountOps, LiveMountScanner
from .discovery import Discovery
from .widgets import (
    MountDialog, MountCard, SectionRow, UnmanagedMountCard, DiscoveryPanel
)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, cfg: ConfigStore, creds: CredentialStore, ops: MountOps):
        super().__init__(application=app)
        self.cfg         = cfg
        self.creds       = creds
        self.ops         = ops
        self.disc        = Discovery()
        self.scanner     = LiveMountScanner()
        self.filter_type = "all"

        self._apply_css()
        self._build()
        self._populate()
        self._auto_mount()
        GLib.timeout_add_seconds(12, self._tick)

    # ── CSS ───────────────────────────────────────────────────────────────────

    def _apply_css(self):
        self.get_style_context().add_class("mb-window")
        p = Gtk.CssProvider()
        p.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        Notify.init(APP_NAME)
        self.set_title(APP_NAME)
        self.set_default_size(920, 600)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Plain vbox — lets xfwm4 draw native window decorations (no CSD).
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        tb = Gtk.Box(spacing=6)
        tb.get_style_context().add_class("mb-toolbar")
        vbox.pack_start(tb, False, False, 0)

        add_btn = Gtk.Button()
        add_btn.set_image(
            Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        )
        add_btn.set_tooltip_text("Add Mount (Ctrl+N)")
        add_btn.set_relief(Gtk.ReliefStyle.NONE)
        add_btn.connect("clicked", self._do_add)
        tb.pack_start(add_btn, False, False, 0)

        ref_btn = Gtk.Button()
        ref_btn.set_image(
            Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        )
        ref_btn.set_tooltip_text("Refresh Status")
        ref_btn.set_relief(Gtk.ReliefStyle.NONE)
        ref_btn.connect("clicked", self._refresh_all)
        tb.pack_start(ref_btn, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_box.set_valign(Gtk.Align.CENTER)
        title_box.set_hexpand(True)
        title_box.set_halign(Gtk.Align.CENTER)
        tl = Gtk.Label(label=APP_NAME)
        tl.get_style_context().add_class("mb-toolbar-title")
        title_box.pack_start(tl, False, False, 0)
        sl = Gtk.Label(label="Network Mount Manager")
        sl.get_style_context().add_class("mb-toolbar-sub")
        title_box.pack_start(sl, False, False, 0)
        tb.pack_start(title_box, True, True, 0)

        self.search_e = Gtk.SearchEntry()
        self.search_e.set_placeholder_text("Search…")
        self.search_e.set_size_request(180, -1)
        self.search_e.connect("search-changed", lambda _: self.lb.invalidate_filter())
        tb.pack_start(self.search_e, False, False, 0)

        self.connect("key-press-event", self._key_press)

        root = Gtk.Box()
        root.set_vexpand(True)
        vbox.pack_start(root, True, True, 0)

        root.pack_start(self._build_sidebar(), False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        root.pack_start(self.stack, True, True, 0)

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

        self.status_lbl = Gtk.Label(label="", xalign=0)
        self.status_lbl.get_style_context().add_class("mb-statusbar")
        mp.pack_start(self.status_lbl, False, False, 0)

        dp = DiscoveryPanel(self.disc, self._add_discovered)
        self.stack.add_named(dp, "discovery")

        vbox.show_all()
        self.stack.set_visible_child_name("mounts")
        self.nav_lb.select_row(self._nav_rows[0])

    def _build_sidebar(self):
        sb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sb.get_style_context().add_class("mb-sidebar")

        def section(parent, text):
            l = Gtk.Label(label=text, xalign=0)
            l.get_style_context().add_class("mb-section-label")
            parent.pack_start(l, False, False, 0)

        section(sb, "MOUNTS")

        self.nav_lb = Gtk.ListBox()
        self.nav_lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_lb.connect("row-selected", self._nav_selected)
        sb.pack_start(self.nav_lb, False, False, 0)

        self._nav_rows = []
        for icon, label, key in [
            ("drive-harddisk-symbolic",    "All Mounts", "all"),
            ("network-server-symbolic",    "NFS",        "nfs"),
            ("network-workgroup-symbolic", "SMB / CIFS", "smb"),
            ("utilities-terminal-symbolic","SSHFS",      "sshfs"),
        ]:
            row = Gtk.ListBoxRow()
            row._key = key
            box = Gtk.Box(spacing=10)
            box.get_style_context().add_class("mb-nav-row")
            row.add(box)
            box.pack_start(
                Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR),
                False, False, 0,
            )
            lw = Gtk.Label(label=label, xalign=0)
            lw.set_hexpand(True)
            box.pack_start(lw, True, True, 0)
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

        section(sb, "TOOLS")

        tools_lb = Gtk.ListBox()
        tools_lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
        tools_lb.connect("row-selected", self._tools_selected)
        sb.pack_start(tools_lb, False, False, 0)

        drow = Gtk.ListBoxRow()
        dbox = Gtk.Box(spacing=10)
        dbox.get_style_context().add_class("mb-nav-row")
        drow.add(dbox)
        dbox.pack_start(
            Gtk.Image.new_from_icon_name("network-wireless-symbolic", Gtk.IconSize.SMALL_TOOLBAR),
            False, False, 0,
        )
        dbox.pack_start(Gtk.Label(label="Discover", xalign=0), True, True, 0)
        tools_lb.add(drow)

        sb.show_all()
        return sb

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _nav_selected(self, lb, row):
        if row and hasattr(self, "lb"):
            self.filter_type = row._key
            self.lb.invalidate_filter()
            self.stack.set_visible_child_name("mounts")

    def _tools_selected(self, lb, row):
        if row:
            self.nav_lb.unselect_all()
            self.stack.set_visible_child_name("discovery")

    # ── Filter ────────────────────────────────────────────────────────────────

    def _filter(self, row):
        if isinstance(row, SectionRow):
            return True
        if isinstance(row, UnmanagedMountCard):
            lm = row.lm
            if self.filter_type != "all" and lm.mount_type != self.filter_type:
                return False
            if not hasattr(self, "search_e"):
                return True
            q = self.search_e.get_text().lower()
            return not q or (
                q in lm.host.lower()
                or q in lm.remote_path.lower()
                or q in lm.local_path.lower()
            )
        if not isinstance(row, MountCard):
            return True
        m = row.mount
        if self.filter_type != "all" and m.mount_type != self.filter_type:
            return False
        if not hasattr(self, "search_e"):
            return True
        q = self.search_e.get_text().lower()
        return not q or (
            q in m.name.lower()
            or q in m.host.lower()
            or q in m.remote_path.lower()
        )

    # ── Populate ──────────────────────────────────────────────────────────────

    def _populate(self):
        for c in self.lb.get_children():
            self.lb.remove(c)

        managed = self.cfg.mounts
        for m in managed:
            self.lb.add(MountCard(m, self.ops, self._do_edit, self._do_delete))

        known_paths = {os.path.realpath(m.local_path) for m in managed}
        unmanaged   = self.scanner.scan(known_paths)

        if unmanaged:
            self.lb.add(SectionRow("UNMANAGED LIVE MOUNTS"))
            for lm in unmanaged:
                self.lb.add(
                    UnmanagedMountCard(lm, self.ops, self._import_live, self._populate)
                )

        if not managed and not unmanaged:
            self._empty_state()

        self.lb.show_all()
        self._update_counts(unmanaged)

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

        s = Gtk.Label(
            label="Add an NFS export, SMB share, or SSHFS connection\nto get started.",
            justify=Gtk.Justification.CENTER,
        )
        s.get_style_context().add_class("mb-empty-sub")
        box.pack_start(s, False, False, 0)

        btn = Gtk.Button(label="  + Add Your First Mount  ")
        btn.get_style_context().add_class("suggested-action")
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect("clicked", self._do_add)
        box.pack_start(btn, False, False, 0)

        self.lb.add(row)

    def _update_counts(self, unmanaged: list = None):
        unmanaged = unmanaged or []
        counts    = {"all": 0, "nfs": 0, "smb": 0, "sshfs": 0}
        mounted   = 0
        for m in self.cfg.mounts:
            counts["all"] += 1
            counts[m.mount_type] = counts.get(m.mount_type, 0) + 1
            if self.ops.is_mounted(m):
                mounted += 1
        for lm in unmanaged:
            counts["all"] += 1
            counts[lm.mount_type] = counts.get(lm.mount_type, 0) + 1
            mounted += 1
        for row in self._nav_rows:
            row._count.set_text(str(counts.get(row._key, 0)))
        total = counts["all"]
        self.status_lbl.set_text(
            f"  {mounted} of {total} mount{'s' if total != 1 else ''} active"
            + (f"  •  {len(unmanaged)} unmanaged" if unmanaged else "")
        )

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _make_config(self, v: dict, fallback_path: str = "") -> MountConfig:
        slug = v["name"].lower().replace(" ", "_").replace("—", "").strip("_")
        return MountConfig(
            id          = str(uuid.uuid4())[:8],
            name        = v["name"],
            mount_type  = v["mount_type"],
            host        = v["host"],
            remote_path = v["remote_path"],
            local_path  = v["local_path"] or fallback_path or str(MOUNTS_DIR / slug),
            username    = v["username"],
            domain      = v["domain"],
            port        = v["port"],
            ssh_key     = v["ssh_key"],
            options     = v["options"],
            auto_mount  = v["auto_mount"],
            created_at  = datetime.now().isoformat(),
        )

    def _do_add(self, *_):
        d = MountDialog(self)
        if d.run() == Gtk.ResponseType.OK:
            v = d.values()
            if v["name"] and v["host"]:
                m = self._make_config(v)
                self.cfg.add(m)
                if v["password"]:
                    self.creds.store(m.id, v["password"])
                self._populate()
        d.destroy()

    def _add_discovered(self, host, path, mtype):
        prefill = type("P", (), {
            "mount_type": mtype, "name": f"{host} — {path or mtype}",
            "host": host, "remote_path": path or "",
            "local_path": "", "username": None, "domain": None,
            "port": None, "ssh_key": None, "options": "", "auto_mount": False,
        })()
        d = MountDialog(self, prefill=prefill)
        if d.run() == Gtk.ResponseType.OK:
            v = d.values()
            m = self._make_config(v)
            self.cfg.add(m)
            if v["password"]:
                self.creds.store(m.id, v["password"])
            self._populate()
            self.stack.set_visible_child_name("mounts")
            self.nav_lb.select_row(self._nav_rows[0])
        d.destroy()

    def _import_live(self, lm: LiveMount):
        """Open the add dialog pre-filled from a live unmanaged mount."""
        prefill = type("P", (), {
            "mount_type":  lm.mount_type,
            "name":        f"{lm.host} — {lm.remote_path}",
            "host":        lm.host,
            "remote_path": lm.remote_path,
            "local_path":  lm.local_path,
            "username":    lm.username,
            "domain":      None,
            "port":        lm.port,
            "ssh_key":     None,
            "options":     lm.options,
            "auto_mount":  False,
        })()
        d = MountDialog(self, prefill=prefill)
        if d.run() == Gtk.ResponseType.OK:
            v = d.values()
            if v["name"] and v["host"]:
                m = self._make_config(v, fallback_path=lm.local_path)
                self.cfg.add(m)
                if v["password"]:
                    self.creds.store(m.id, v["password"])
                self._populate()
        d.destroy()

    def _do_edit(self, mount: MountConfig):
        d = MountDialog(self, mount=mount)
        if d.run() == Gtk.ResponseType.OK:
            v = d.values()
            mount.name        = v["name"]
            mount.mount_type  = v["mount_type"]
            mount.host        = v["host"]
            mount.remote_path = v["remote_path"]
            mount.local_path  = v["local_path"]
            mount.username    = v["username"]
            mount.domain      = v["domain"]
            mount.port        = v["port"]
            mount.ssh_key     = v["ssh_key"]
            mount.options     = v["options"]
            mount.auto_mount  = v["auto_mount"]
            self.cfg.update(mount)
            if v["password"]:
                self.creds.store(mount.id, v["password"])
            self._populate()
        d.destroy()

    def _do_delete(self, mount: MountConfig):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f'Remove "{mount.name}"?',
        )
        dlg.format_secondary_text(
            "The mount configuration and stored credentials will be deleted. "
            "The mounted filesystem and its data are not affected."
        )
        if dlg.run() == Gtk.ResponseType.YES:
            if self.ops.is_mounted(mount):
                self.ops.unmount(mount)
            self.creds.delete(mount.id)
            self.cfg.delete(mount.id)
            self._populate()
        dlg.destroy()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _refresh_all(self, *_):
        for r in self.lb.get_children():
            if isinstance(r, MountCard):
                threading.Thread(target=r.refresh, daemon=True).start()
        GLib.timeout_add(600, self._rescan_unmanaged)

    def _rescan_unmanaged(self):
        GLib.idle_add(self._populate)
        return False

    def _tick(self):
        self._refresh_all()
        return True

    def _auto_mount(self):
        for m in self.cfg.mounts:
            if m.auto_mount and not self.ops.is_mounted(m):
                threading.Thread(target=self.ops.mount, args=(m,), daemon=True).start()

    def _key_press(self, _, ev):
        if ev.state & Gdk.ModifierType.CONTROL_MASK and ev.keyval == ord("n"):
            self._do_add()


# ── Application ───────────────────────────────────────────────────────────────

class MountBridgeApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.cfg   = ConfigStore()
        self.creds = CredentialStore()
        self.ops   = MountOps(self.creds)
        self.win   = None

    def do_activate(self):
        if not self.win:
            self.win = MainWindow(self, self.cfg, self.creds, self.ops)
            self._tray()
        self.win.present()

    def _tray(self):
        if HAS_INDICATOR:
            try:
                ind = AppIndicator3.Indicator.new(
                    APP_ID, "drive-harddisk-symbolic",
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                )
                ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
                menu  = Gtk.Menu()
                show  = Gtk.MenuItem(label=f"Open {APP_NAME}")
                show.connect("activate", lambda _: self.win.present())
                menu.append(show)
                menu.append(Gtk.SeparatorMenuItem())
                quit_ = Gtk.MenuItem(label="Quit")
                quit_.connect("activate", lambda _: self.quit())
                menu.append(quit_)
                menu.show_all()
                ind.set_menu(menu)
                return
            except Exception:
                pass
        try:
            si = Gtk.StatusIcon.new_from_icon_name("drive-harddisk-symbolic")
            si.set_tooltip_text(APP_NAME)
            si.connect("activate", lambda _: self.win.present())
        except Exception:
            pass


def main():
    app = MountBridgeApp()
    sys.exit(app.run(sys.argv))
