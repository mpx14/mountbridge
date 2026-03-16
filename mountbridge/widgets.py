"""GTK3 widget classes: dialogs, cards, discovery panel."""
import subprocess
import threading
from pathlib import Path
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, GLib, Notify

from .constants import MOUNTS_DIR
from .models import MountConfig, MountType, MountStatus, LiveMount
from .ops import MountOps
from .discovery import Discovery


# ── Add / Edit mount dialog ───────────────────────────────────────────────────

class MountDialog(Gtk.Dialog):
    def __init__(self, parent, mount: Optional[MountConfig] = None, prefill=None):
        super().__init__(transient_for=parent, modal=True, use_header_bar=True)
        self.set_title("Edit Mount" if mount else "Add Mount")
        self.set_default_size(500, -1)
        self.edit = mount
        self._build(mount or prefill)

    def _build(self, m=None):
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save = self.add_button("Save Mount", Gtk.ResponseType.OK)
        save.get_style_context().add_class("suggested-action")

        c = self.get_content_area()
        c.set_spacing(0)
        c.set_margin_start(22)
        c.set_margin_end(22)
        c.set_margin_top(10)
        c.set_margin_bottom(18)

        self._lbl(c, "TYPE")
        self.type_combo = Gtk.ComboBoxText()
        for t in ["NFS", "SMB / CIFS", "SSHFS"]:
            self.type_combo.append_text(t)
        idx = 0
        if m:
            try:
                idx = ["nfs", "smb", "sshfs"].index(getattr(m, "mount_type", "nfs"))
            except ValueError:
                idx = 0
        self.type_combo.set_active(idx)
        self.type_combo.connect("changed", self._type_changed)
        c.pack_start(self.type_combo, False, False, 4)

        self._lbl(c, "DISPLAY NAME")
        self.name_e = self._entry(c, "e.g. Home NAS, Media Server", m, "name")

        self._lbl(c, "HOST")
        self.host_e = self._entry(c, "Hostname or IP address", m, "host")

        self._lbl(c, "REMOTE PATH / SHARE")
        self.remote_e = self._entry(c, "/export/path  or  sharename", m, "remote_path")

        self._lbl(c, "LOCAL MOUNT POINT")
        lbox = Gtk.Box(spacing=5)
        c.pack_start(lbox, False, False, 4)
        self.local_e = Gtk.Entry()
        self.local_e.set_placeholder_text(f"{MOUNTS_DIR}/my-share")
        self.local_e.get_style_context().add_class("mb-entry")
        self.local_e.set_hexpand(True)
        if m and getattr(m, "local_path", ""):
            self.local_e.set_text(m.local_path)
        lbox.pack_start(self.local_e, True, True, 0)
        bb = Gtk.Button(label="Browse…")
        bb.connect("clicked", self._browse_local)
        lbox.pack_start(bb, False, False, 0)

        # Credentials (hidden for NFS)
        self.creds_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        c.pack_start(self.creds_box, False, False, 0)

        self._lbl(self.creds_box, "CREDENTIALS")
        grd = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.creds_box.pack_start(grd, False, False, 4)

        self.user_e = Gtk.Entry()
        self.user_e.set_placeholder_text("Username")
        self.user_e.get_style_context().add_class("mb-entry")
        self.user_e.set_hexpand(True)
        if m and getattr(m, "username", None):
            self.user_e.set_text(m.username)
        grd.attach(self.user_e, 0, 0, 1, 1)

        self.pass_e = Gtk.Entry()
        self.pass_e.set_placeholder_text("Password (stored in keyring)")
        self.pass_e.set_visibility(False)
        self.pass_e.get_style_context().add_class("mb-entry")
        self.pass_e.set_hexpand(True)
        grd.attach(self.pass_e, 1, 0, 1, 1)

        # SSH options (SSHFS only)
        self.ssh_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        c.pack_start(self.ssh_box, False, False, 0)

        self._lbl(self.ssh_box, "SSH PORT")
        self.port_e = self._entry(self.ssh_box, "22", m, "port",
                                  transform=lambda v: str(v) if v else "")

        self._lbl(self.ssh_box, "SSH PRIVATE KEY (OPTIONAL)")
        kbox = Gtk.Box(spacing=5)
        self.ssh_box.pack_start(kbox, False, False, 4)
        self.key_e = Gtk.Entry()
        self.key_e.set_placeholder_text("~/.ssh/id_ed25519  (leave blank to use password)")
        self.key_e.get_style_context().add_class("mb-entry")
        self.key_e.set_hexpand(True)
        if m and getattr(m, "ssh_key", None):
            self.key_e.set_text(m.ssh_key)
        kbox.pack_start(self.key_e, True, True, 0)
        kb = Gtk.Button(label="Browse…")
        kb.connect("clicked", self._browse_key)
        kbox.pack_start(kb, False, False, 0)

        # Windows domain (SMB only)
        self.domain_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        c.pack_start(self.domain_box, False, False, 0)
        self._lbl(self.domain_box, "WINDOWS DOMAIN (OPTIONAL)")
        self.domain_e = self._entry(self.domain_box, "WORKGROUP", m, "domain")

        self._lbl(c, "EXTRA MOUNT OPTIONS (OPTIONAL)")
        self.opts_e = self._entry(c, "Comma-separated, e.g. ro,noatime", m, "options")

        arow = Gtk.Box(spacing=12)
        arow.set_margin_top(12)
        c.pack_start(arow, False, False, 0)
        al = Gtk.Label(label="Auto-mount on login", xalign=0)
        al.set_hexpand(True)
        arow.pack_start(al, True, True, 0)
        self.auto_sw = Gtk.Switch()
        self.auto_sw.set_valign(Gtk.Align.CENTER)
        if m:
            self.auto_sw.set_active(getattr(m, "auto_mount", False))
        arow.pack_start(self.auto_sw, False, False, 0)

        self.show_all()
        self._type_changed(self.type_combo)

    def _lbl(self, parent, text):
        l = Gtk.Label(label=text, xalign=0)
        l.get_style_context().add_class("mb-field-label")
        parent.pack_start(l, False, False, 0)

    def _entry(self, parent, placeholder, m, attr, transform=None):
        e = Gtk.Entry()
        e.set_placeholder_text(placeholder)
        e.get_style_context().add_class("mb-entry")
        val = getattr(m, attr, "") if m else ""
        if val and transform:
            val = transform(val)
        if val:
            e.set_text(str(val))
        parent.pack_start(e, False, False, 4)
        return e

    def _type_changed(self, combo):
        types = ["nfs", "smb", "sshfs"]
        idx   = combo.get_active()
        t     = types[idx] if 0 <= idx < 3 else "nfs"
        self.creds_box.set_visible(t != "nfs")
        self.ssh_box.set_visible(t == "sshfs")
        self.domain_box.set_visible(t == "smb")
        if t == "nfs":
            self.remote_e.set_placeholder_text("/exports/data")
        elif t == "smb":
            self.remote_e.set_placeholder_text("sharename")
        else:
            self.remote_e.set_placeholder_text("/home/user  or  /")

    def _browse_local(self, _):
        d = Gtk.FileChooserDialog(
            "Choose Mount Point", self, Gtk.FileChooserAction.SELECT_FOLDER,
            ["Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK],
        )
        d.set_current_folder(str(MOUNTS_DIR))
        if d.run() == Gtk.ResponseType.OK:
            self.local_e.set_text(d.get_filename())
        d.destroy()

    def _browse_key(self, _):
        d = Gtk.FileChooserDialog(
            "Choose SSH Key", self, Gtk.FileChooserAction.OPEN,
            ["Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK],
        )
        d.set_current_folder(str(Path.home() / ".ssh"))
        if d.run() == Gtk.ResponseType.OK:
            self.key_e.set_text(d.get_filename())
        d.destroy()

    def values(self) -> dict:
        types = ["nfs", "smb", "sshfs"]
        idx   = self.type_combo.get_active()
        mtype = types[idx] if 0 <= idx < 3 else "nfs"
        ps    = self.port_e.get_text().strip()
        return {
            "mount_type":  mtype,
            "name":        self.name_e.get_text().strip(),
            "host":        self.host_e.get_text().strip(),
            "remote_path": self.remote_e.get_text().strip(),
            "local_path":  self.local_e.get_text().strip(),
            "username":    self.user_e.get_text().strip() or None,
            "password":    self.pass_e.get_text(),
            "ssh_key":     self.key_e.get_text().strip() or None,
            "domain":      self.domain_e.get_text().strip() or None,
            "port":        int(ps) if ps.isdigit() else None,
            "options":     self.opts_e.get_text().strip(),
            "auto_mount":  self.auto_sw.get_active(),
        }


# ── Managed mount card ────────────────────────────────────────────────────────

class MountCard(Gtk.ListBoxRow):
    def __init__(self, mount: MountConfig, ops: MountOps, on_edit, on_delete):
        super().__init__()
        self.mount     = mount
        self.ops       = ops
        self.on_edit   = on_edit
        self.on_delete = on_delete
        self.status    = MountStatus.UNMOUNTED
        self.get_style_context().add_class("mb-card")
        self._build()
        self.refresh()

    def _build(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_margin_start(14)
        outer.set_margin_end(14)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        self.add(outer)

        top = Gtk.Box(spacing=8)
        top.set_valign(Gtk.Align.CENTER)
        outer.pack_start(top, False, False, 0)

        badge = Gtk.Label(label=self.mount.mount_type.upper())
        badge.get_style_context().add_class("mb-type")
        badge.get_style_context().add_class(f"mb-type-{self.mount.mount_type}")
        top.pack_start(badge, False, False, 0)

        name_lbl = Gtk.Label(label=self.mount.name, xalign=0)
        name_lbl.get_style_context().add_class("mb-name")
        name_lbl.set_hexpand(True)
        name_lbl.set_ellipsize(3)
        top.pack_start(name_lbl, True, True, 0)

        self.dot = Gtk.Box()
        self.dot.get_style_context().add_class("mb-dot")
        self.dot.get_style_context().add_class("mb-dot-off")
        top.pack_start(self.dot, False, False, 0)

        mt = MountType(self.mount.mount_type)
        if mt == MountType.SMB:
            remote = f"\\\\{self.mount.host}\\{self.mount.remote_path}"
        elif mt == MountType.NFS:
            remote = f"{self.mount.host}:{self.mount.remote_path}"
        else:
            u      = self.mount.username or ""
            remote = (f"{u}@{self.mount.host}:{self.mount.remote_path}" if u
                      else f"{self.mount.host}:{self.mount.remote_path}")

        path_lbl = Gtk.Label(label=f"{remote}  →  {self.mount.local_path}", xalign=0)
        path_lbl.get_style_context().add_class("mb-remote")
        path_lbl.set_ellipsize(3)
        path_lbl.set_margin_top(4)
        outer.pack_start(path_lbl, False, False, 0)

        if self.mount.auto_mount:
            al = Gtk.Label(label="⟳ auto-mount", xalign=0)
            al.set_opacity(0.45)
            al.set_margin_top(2)
            outer.pack_start(al, False, False, 0)

        acts = Gtk.Box(spacing=6)
        acts.set_margin_top(10)
        outer.pack_start(acts, False, False, 0)

        self.mount_btn = Gtk.Button(label="Mount")
        self.mount_btn.get_style_context().add_class("mb-btn")
        self.mount_btn.get_style_context().add_class("mb-btn-mount")
        self.mount_btn.connect("clicked", self._toggle)
        acts.pack_start(self.mount_btn, False, False, 0)

        self.open_btn = Gtk.Button(label="Open Folder")
        self.open_btn.get_style_context().add_class("mb-btn")
        self.open_btn.get_style_context().add_class("mb-btn-secondary")
        self.open_btn.connect(
            "clicked",
            lambda _: subprocess.Popen(["xdg-open", self.mount.local_path]),
        )
        self.open_btn.set_sensitive(False)
        acts.pack_start(self.open_btn, False, False, 0)

        spacer = Gtk.Label()
        spacer.set_hexpand(True)
        acts.pack_start(spacer, True, True, 0)

        edit_btn = Gtk.Button()
        edit_btn.set_image(
            Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        )
        edit_btn.set_tooltip_text("Edit")
        edit_btn.connect("clicked", lambda _: self.on_edit(self.mount))
        acts.pack_start(edit_btn, False, False, 0)

        del_btn = Gtk.Button()
        del_btn.set_image(
            Gtk.Image.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        )
        del_btn.set_tooltip_text("Remove")
        del_btn.connect("clicked", lambda _: self.on_delete(self.mount))
        acts.pack_start(del_btn, False, False, 0)

        self.show_all()

    def refresh(self):
        mounted    = self.ops.is_mounted(self.mount)
        self.status = MountStatus.MOUNTED if mounted else MountStatus.UNMOUNTED
        GLib.idle_add(self._apply_status)

    def _apply_status(self):
        ctx = self.dot.get_style_context()
        for c in ["mb-dot-on", "mb-dot-off", "mb-dot-busy", "mb-dot-err"]:
            ctx.remove_class(c)
        ctx.add_class(f"mb-dot-{self.status.value}")

        is_on   = self.status == MountStatus.MOUNTED
        is_busy = self.status == MountStatus.BUSY

        self.open_btn.set_sensitive(is_on)
        self.mount_btn.set_sensitive(not is_busy)

        ctx2 = self.mount_btn.get_style_context()
        if is_on:
            self.mount_btn.set_label("Unmount")
            ctx2.remove_class("mb-btn-mount")
            ctx2.add_class("mb-btn-unmount")
        elif is_busy:
            self.mount_btn.set_label("Working…")
        else:
            self.mount_btn.set_label("Mount")
            ctx2.remove_class("mb-btn-unmount")
            ctx2.add_class("mb-btn-mount")

    def _toggle(self, _):
        self.status = MountStatus.BUSY
        self._apply_status()

        def work():
            if self.ops.is_mounted(self.mount):
                ok, msg = self.ops.unmount(self.mount)
            else:
                ok, msg = self.ops.mount(self.mount)
            GLib.idle_add(self._done, ok, msg)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, ok, msg):
        self.refresh()
        if Notify.is_initted():
            icon = "drive-harddisk-symbolic" if ok else "dialog-error-symbolic"
            Notify.Notification.new(self.mount.name, msg, icon).show()


# ── Section divider ───────────────────────────────────────────────────────────

class SectionRow(Gtk.ListBoxRow):
    """Non-interactive label row separating managed and unmanaged sections."""

    def __init__(self, text: str):
        super().__init__()
        self.set_selectable(False)
        self.set_activatable(False)
        self._section_text = text
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.get_style_context().add_class("mb-section-divider")
        self.add(lbl)
        self.show_all()


# ── Unmanaged mount card ──────────────────────────────────────────────────────

class UnmanagedMountCard(Gtk.ListBoxRow):
    """Card for a live network mount not tracked in the MountBridge config."""

    def __init__(self, lm: LiveMount, ops: MountOps, on_import, on_unmount_done):
        super().__init__()
        self.lm              = lm
        self.ops             = ops
        self.on_import       = on_import
        self.on_unmount_done = on_unmount_done
        self.get_style_context().add_class("mb-card-unmanaged")
        self._build()

    def _build(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_margin_start(14)
        outer.set_margin_end(14)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        self.add(outer)

        top = Gtk.Box(spacing=8)
        top.set_valign(Gtk.Align.CENTER)
        outer.pack_start(top, False, False, 0)

        tb = Gtk.Label(label=self.lm.mount_type.upper())
        tb.get_style_context().add_class("mb-type")
        tb.get_style_context().add_class(f"mb-type-{self.lm.mount_type}")
        top.pack_start(tb, False, False, 0)

        lb = Gtk.Label(label="LIVE")
        lb.get_style_context().add_class("mb-type")
        lb.get_style_context().add_class("mb-type-live")
        top.pack_start(lb, False, False, 0)

        name_lbl = Gtk.Label(label=f"{self.lm.host} — {self.lm.remote_path}", xalign=0)
        name_lbl.get_style_context().add_class("mb-name")
        name_lbl.set_hexpand(True)
        name_lbl.set_ellipsize(3)
        top.pack_start(name_lbl, True, True, 0)

        dot = Gtk.Box()
        dot.get_style_context().add_class("mb-dot")
        dot.get_style_context().add_class("mb-dot-on")
        top.pack_start(dot, False, False, 0)

        path_lbl = Gtk.Label(
            label=f"{self.lm.device}  →  {self.lm.local_path}", xalign=0
        )
        path_lbl.get_style_context().add_class("mb-remote")
        path_lbl.set_ellipsize(3)
        path_lbl.set_margin_top(4)
        outer.pack_start(path_lbl, False, False, 0)

        note = Gtk.Label(
            label="Not managed by MountBridge — import to track, edit and auto-mount it.",
            xalign=0,
        )
        note.get_style_context().add_class("mb-unmanaged-note")
        outer.pack_start(note, False, False, 0)

        acts = Gtk.Box(spacing=6)
        acts.set_margin_top(10)
        outer.pack_start(acts, False, False, 0)

        import_btn = Gtk.Button(label="Import to Config")
        import_btn.get_style_context().add_class("mb-btn")
        import_btn.get_style_context().add_class("mb-btn-mount")
        import_btn.connect("clicked", lambda _: self.on_import(self.lm))
        acts.pack_start(import_btn, False, False, 0)

        open_btn = Gtk.Button(label="Open Folder")
        open_btn.get_style_context().add_class("mb-btn")
        open_btn.get_style_context().add_class("mb-btn-secondary")
        open_btn.connect(
            "clicked",
            lambda _: subprocess.Popen(["xdg-open", self.lm.local_path]),
        )
        acts.pack_start(open_btn, False, False, 0)

        spacer = Gtk.Label()
        spacer.set_hexpand(True)
        acts.pack_start(spacer, True, True, 0)

        self.unmount_btn = Gtk.Button(label="Unmount")
        self.unmount_btn.get_style_context().add_class("mb-btn")
        self.unmount_btn.get_style_context().add_class("mb-btn-unmount")
        self.unmount_btn.connect("clicked", self._do_unmount)
        acts.pack_start(self.unmount_btn, False, False, 0)

        self.show_all()

    def _do_unmount(self, _):
        self.unmount_btn.set_label("Working…")
        self.unmount_btn.set_sensitive(False)
        dummy = MountConfig(
            id="", name="", mount_type=self.lm.mount_type,
            host=self.lm.host, remote_path=self.lm.remote_path,
            local_path=self.lm.local_path,
        )

        def work():
            ok, msg = self.ops.unmount(dummy)
            GLib.idle_add(self._unmount_done, ok, msg)

        threading.Thread(target=work, daemon=True).start()

    def _unmount_done(self, ok, msg):
        if Notify.is_initted():
            icon = "drive-harddisk-symbolic" if ok else "dialog-error-symbolic"
            Notify.Notification.new(self.lm.host, msg, icon).show()
        self.on_unmount_done()


# ── Network discovery panel ───────────────────────────────────────────────────

class DiscoveryPanel(Gtk.Box):
    def __init__(self, disc: Discovery, on_add):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.disc   = disc
        self.on_add = on_add
        self._build()

    def _build(self):
        tb = Gtk.Box(spacing=8)
        tb.set_margin_start(12)
        tb.set_margin_end(12)
        tb.set_margin_top(14)
        tb.set_margin_bottom(10)
        self.pack_start(tb, False, False, 0)

        self.mode_combo = Gtk.ComboBoxText()
        for t in ["SMB broadcast", "SMB shares on host", "NFS exports on host"]:
            self.mode_combo.append_text(t)
        self.mode_combo.set_active(0)
        self.mode_combo.connect("changed", self._mode_changed)
        tb.pack_start(self.mode_combo, False, False, 0)

        self.host_e = Gtk.Entry()
        self.host_e.set_placeholder_text("Target host (for SMB shares / NFS)")
        self.host_e.set_hexpand(True)
        self.host_e.set_no_show_all(True)
        self.host_e.hide()
        tb.pack_start(self.host_e, True, True, 0)

        scan_btn = Gtk.Button(label="Scan Network")
        scan_btn.get_style_context().add_class("suggested-action")
        scan_btn.connect("clicked", self._scan)
        tb.pack_start(scan_btn, False, False, 0)

        self.spinner = Gtk.Spinner()
        tb.pack_start(self.spinner, False, False, 0)

        self.pack_start(Gtk.Separator(), False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.pack_start(scroll, True, True, 0)

        self.lb = Gtk.ListBox()
        self.lb.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.lb)

        self._add_hint("Use the scanner above to find NFS and SMB shares on your network.")
        self.show_all()

    def _mode_changed(self, combo):
        need = combo.get_active() in (1, 2)
        self.host_e.show() if need else self.host_e.hide()

    def _clear(self):
        for r in self.lb.get_children():
            self.lb.remove(r)

    def _add_hint(self, text):
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        lbl = Gtk.Label(label=text, xalign=0, wrap=True)
        lbl.set_opacity(0.45)
        lbl.set_margin_start(14)
        lbl.set_margin_top(16)
        row.add(lbl)
        self.lb.add(row)
        self.lb.show_all()

    def _scan(self, _):
        self._clear()
        self.spinner.start()
        mode = self.mode_combo.get_active()
        host = self.host_e.get_text().strip()
        if mode == 0:
            self.disc.smb_broadcast(self._on_broadcast)
        elif mode == 1:
            if not host:
                self._add_hint("Enter a target host first.")
                self.spinner.stop()
                return
            self.disc.smb_shares(host, "", "", self._on_smb_shares)
        elif mode == 2:
            if not host:
                self._add_hint("Enter a target host first.")
                self.spinner.stop()
                return
            self.disc.nfs_exports(host, self._on_nfs_exports)

    def _on_broadcast(self, results):
        self.spinner.stop()
        if not results:
            self._add_hint("No SMB hosts found via Avahi. Try specifying a host directly.")
            return
        for r in results:
            self._result_row(r["host"], None, "smb", r.get("detail", ""))
        self.lb.show_all()

    def _on_smb_shares(self, host, shares):
        self.spinner.stop()
        if not shares:
            self._add_hint(f"No shares found on {host}.")
            return
        for s in shares:
            self._result_row(host, s, "smb", f"\\\\{host}\\{s}")
        self.lb.show_all()

    def _on_nfs_exports(self, host, exports):
        self.spinner.stop()
        if not exports:
            self._add_hint(f"No NFS exports found on {host}.")
            return
        for p in exports:
            self._result_row(host, p, "nfs", f"{host}:{p}")
        self.lb.show_all()

    def _result_row(self, host, path, mtype, detail):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12)
        box.get_style_context().add_class("mb-disc-row")
        row.add(box)

        icons = {
            "smb":   "network-workgroup-symbolic",
            "nfs":   "drive-harddisk-symbolic",
            "sshfs": "network-server-symbolic",
        }
        box.pack_start(
            Gtk.Image.new_from_icon_name(
                icons.get(mtype, "network-server-symbolic"), Gtk.IconSize.BUTTON
            ),
            False, False, 0,
        )

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)
        box.pack_start(info, True, True, 0)

        h = Gtk.Label(label=host, xalign=0)
        h.get_style_context().add_class("mb-disc-host")
        info.pack_start(h, False, False, 0)

        if detail:
            d = Gtk.Label(label=detail, xalign=0)
            d.get_style_context().add_class("mb-disc-detail")
            info.pack_start(d, False, False, 0)

        badge = Gtk.Label(label=mtype.upper())
        badge.get_style_context().add_class("mb-type")
        badge.get_style_context().add_class(f"mb-type-{mtype}")
        box.pack_start(badge, False, False, 0)

        add_btn = Gtk.Button(label="Add Mount")
        add_btn.connect(
            "clicked",
            lambda _, h=host, p=path, t=mtype: self.on_add(h, p, t),
        )
        box.pack_start(add_btn, False, False, 0)

        self.lb.add(row)
