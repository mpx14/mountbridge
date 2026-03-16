"""Application-wide constants, paths and stylesheet."""
from pathlib import Path

APP_ID      = "net.mutefx.mountbridge"
APP_NAME    = "MountBridge"
APP_VERSION = "1.1.0"

CONFIG_DIR  = Path.home() / ".config" / "mountbridge"
MOUNTS_DIR  = Path.home() / ".mounts"
CONFIG_FILE = CONFIG_DIR / "mounts.json"
KEYRING_SVC = "mountbridge"

CSS = """
/* -- Base ------------------------------------------------- */
.mb-window { background-color: @theme_bg_color; }

/* -- Toolbar ---------------------------------------------- */
.mb-toolbar {
    background-color: shade(@theme_bg_color, 0.94);
    border-bottom: 1px solid shade(@theme_bg_color, 0.70);
    padding: 4px 8px;
    min-height: 38px;
}
.mb-toolbar-title { font-size: 13px; font-weight: 700; }
.mb-toolbar-sub   { font-size: 10px; color: alpha(@theme_fg_color, 0.50); }

/* -- Sidebar ---------------------------------------------- */
.mb-sidebar {
    background-color: shade(@theme_bg_color, 0.88);
    border-right: 1px solid shade(@theme_bg_color, 0.68);
    min-width: 192px;
}
.mb-section-label {
    font-size: 10px; font-weight: 800; letter-spacing: 1.2px;
    color: alpha(@theme_fg_color, 0.42);
    margin: 14px 14px 4px 14px;
}
.mb-nav-row {
    padding: 7px 12px; border-radius: 6px; margin: 1px 6px;
    transition: background-color 120ms;
}
.mb-nav-row:hover              { background-color: alpha(@theme_fg_color, 0.07); }
.mb-nav-row:selected,
.mb-nav-row:selected:hover     { background-color: @theme_selected_bg_color;
                                  color: @theme_selected_fg_color; }
.mb-nav-row label              { font-size: 13px; }
.mb-badge {
    background-color: alpha(@theme_fg_color, 0.11);
    border-radius: 9px; padding: 1px 7px;
    font-size: 10px; font-weight: 700; min-width: 18px;
}
.mb-nav-row:selected .mb-badge { background-color: alpha(@theme_selected_fg_color, 0.22); }

/* -- Cards ------------------------------------------------ */
.mb-card {
    background-color: @theme_base_color;
    border: 1px solid shade(@theme_bg_color, 0.72);
    border-radius: 9px; margin: 4px 10px;
    transition: border-color 150ms;
}
.mb-card:hover { border-color: alpha(@theme_selected_bg_color, 0.7); }

/* -- Type badges ------------------------------------------ */
.mb-type {
    border-radius: 4px; padding: 2px 8px;
    font-size: 9px; font-weight: 800; letter-spacing: 0.8px;
}
.mb-type-nfs   { background-color: alpha(#5294e2, 0.14); color: #5294e2; }
.mb-type-smb   { background-color: alpha(#f0883e, 0.14); color: #d07030; }
.mb-type-sshfs { background-color: alpha(#4fc3a1, 0.14); color: #2da882; }

/* -- Mount name & path ------------------------------------ */
.mb-name   { font-size: 14px; font-weight: 700; }
.mb-remote { font-family: monospace; font-size: 11px; color: alpha(@theme_fg_color, 0.55); }

/* -- Status dots ------------------------------------------ */
.mb-dot { border-radius: 50%; min-width: 9px; min-height: 9px; margin: 1px 4px; }
.mb-dot-on   { background-color: #4fc3a1; box-shadow: 0 0 0 3px alpha(#4fc3a1, 0.22); }
.mb-dot-off  { background-color: alpha(@theme_fg_color, 0.18); }
.mb-dot-busy { background-color: #f0a830; box-shadow: 0 0 0 3px alpha(#f0a830, 0.22); }
.mb-dot-err  { background-color: #e05c5c; box-shadow: 0 0 0 3px alpha(#e05c5c, 0.22); }

/* -- Buttons ---------------------------------------------- */
.mb-btn { border-radius: 6px; padding: 4px 12px; font-size: 12px; font-weight: 600; }
.mb-btn-mount {
    background-color: alpha(@theme_selected_bg_color, 0.9);
    color: @theme_selected_fg_color; border: none;
}
.mb-btn-unmount {
    background-color: alpha(#e05c5c, 0.10); color: #c04040;
    border: 1px solid alpha(#e05c5c, 0.30);
}
.mb-btn-secondary {
    background-color: alpha(@theme_fg_color, 0.06);
    border: 1px solid alpha(@theme_fg_color, 0.14);
}

/* -- Empty state ------------------------------------------ */
.mb-empty        { padding: 56px 20px; }
.mb-empty-icon   { color: alpha(@theme_fg_color, 0.12); }
.mb-empty-title  {
    font-size: 18px; font-weight: 700;
    color: alpha(@theme_fg_color, 0.4); margin-top: 12px;
}
.mb-empty-sub    {
    font-size: 13px; color: alpha(@theme_fg_color, 0.32);
    margin-top: 6px; margin-bottom: 20px;
}

/* -- Status bar ------------------------------------------- */
.mb-statusbar {
    background-color: shade(@theme_bg_color, 0.88);
    border-top: 1px solid shade(@theme_bg_color, 0.72);
    padding: 4px 14px; font-size: 11px;
    color: alpha(@theme_fg_color, 0.55);
}

/* -- Dialog fields ---------------------------------------- */
.mb-field-label {
    font-size: 10px; font-weight: 800; letter-spacing: 1px;
    color: alpha(@theme_fg_color, 0.45);
    margin-top: 14px; margin-bottom: 3px;
}
.mb-entry { border-radius: 6px; }

/* -- Discovery -------------------------------------------- */
.mb-disc-row   { padding: 9px 14px; }
.mb-disc-host  { font-size: 13px; font-weight: 600; }
.mb-disc-detail {
    font-size: 11px; font-family: monospace;
    color: alpha(@theme_fg_color, 0.52);
}

/* -- Unmanaged live mounts -------------------------------- */
.mb-card-unmanaged {
    background-color: @theme_base_color;
    border: 1px solid alpha(#f0a830, 0.35);
    border-left: 3px solid alpha(#f0a830, 0.70);
    border-radius: 9px; margin: 4px 10px;
}
.mb-card-unmanaged:hover { border-color: alpha(#f0a830, 0.65); }
.mb-type-live { background-color: alpha(#f0a830, 0.15); color: #c07800; }
.mb-unmanaged-note {
    font-size: 11px; color: alpha(@theme_fg_color, 0.50);
    font-style: italic; margin-top: 3px;
}

/* -- Section divider -------------------------------------- */
.mb-section-divider {
    font-size: 10px; font-weight: 800; letter-spacing: 1.2px;
    color: alpha(@theme_fg_color, 0.38);
    padding: 14px 14px 4px 18px;
}
"""
