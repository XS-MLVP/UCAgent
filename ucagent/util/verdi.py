"""Generate injection-safe Verdi playback for original waveform evidence."""

from pathlib import Path


def tcl_string(value: str) -> str:
    """Encode arbitrary UTF-8 as a Tcl expression without command substitution."""
    return '[encoding convertfrom utf-8 [binary decode hex {' + value.encode().hex() + '}]]'


def render_verdi_playback(waveform: Path, payload: dict, status_dir: Path) -> str:
    """Load the original waveform, select evidence signals and align raw timestamps."""
    assignments = [f"set waveform {tcl_string(str(waveform))}",
                   f"set status_dir {tcl_string(str(status_dir))}"]
    signals = payload.get("signals", [])
    assignments.append("set signals [list " + " ".join(
        tcl_string(signal if signal.startswith("/") else "/" + signal.replace(".", "/"))
        for signal in signals) + "]")
    for key in ("start", "end", "cursor"):
        assignments.append(f"set {key} {tcl_string(payload.get(key, ''))}")
    return "\n".join(assignments) + r'''
proc unit_seconds {unit} {
    if {![regexp {^([0-9.]+)?\s*([fpnumsKMG]+)$} [string trim $unit] unused factor suffix]} {
        error "Unsupported waveform time unit: $unit"
    }
    if {$factor eq ""} {set factor 1}
    set scales [dict create f 1e-15 fs 1e-15 p 1e-12 ps 1e-12 n 1e-9 ns 1e-9 u 1e-6 us 1e-6 m 1e-3 ms 1e-3 s 1 K 1e3 M 1e6 G 1e9]
    return [expr {$factor * [dict get $scales $suffix]}]
}
if {[catch {
    set window [wvCreateWindow]
    set opened [wvOpenFile -win $window $waveform]
    if {$opened eq "0" || $opened eq ""} {error "Cannot open waveform"}
    foreach signal $signals {
        if {![wvAddSignal -win $window $signal]} {error "Cannot add signal: $signal"}
    }
    if {$start ne ""} {
        set ratio [expr {[unit_seconds [wvGetFileTimeUnit -win $window]] / [unit_seconds [wvGetWindowTimeUnit -win $window]]}]
        wvZoom -win $window [expr {$start * $ratio}] [expr {$end * $ratio}]
        wvSetCursor -win $window [expr {$cursor * $ratio}]
    }
    wvResizeWindow -win $window 0 0 1200 700
    wvRaiseWindow -win $window
} problem]} {
    set status [open [file join $status_dir error.txt] w]
    puts $status $problem
    close $status
} else {
    set status [open [file join $status_dir ready.txt] w]
    puts $status "Original waveform loaded; signals=$signals; cursor=$cursor"
    close $status
}
'''
