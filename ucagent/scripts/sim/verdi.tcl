# Load original waveform evidence in a docked Verdi window.
proc unit_seconds {unit} {
    if {![regexp {^([0-9.]+)?\s*([fpnumsKMG]+)$} [string trim $unit] unused factor suffix]} {
        error "Unsupported waveform time unit: $unit"
    }
    if {$factor eq ""} {set factor 1}
    set scales [dict create f 1e-15 fs 1e-15 p 1e-12 ps 1e-12 n 1e-9 ns 1e-9 u 1e-6 us 1e-6 m 1e-3 ms 1e-3 s 1 K 1e3 M 1e6 G 1e9]
    return [expr {$factor * [dict get $scales $suffix]}]
}
source $env(UCAGENT_WAVE_DATA)
if {[catch {
    set database [open [file join $daidir simv.kdb] r]
    set metadata [read $database]
    close $database
    if {[string first "KDB=TRUE" $metadata] < 0} {error "Design database requires VCS -kdb"}
    verdiSetPrefEnv -bUndockNewCreatedWindow off
    set window [wvCreateWindow]
    set opened [wvOpenFile -win $window $file]
    if {$opened eq "0" || $opened eq ""} {error "Cannot open waveform"}
    foreach signal $signals {
        if {![string match /* $signal]} {set signal /[string map {. /} $signal]}
        if {![wvAddSignal -win $window $signal]} {error "Cannot add signal: $signal"}
    }
    if {$start ne ""} {
        set ratio [expr {[unit_seconds [wvGetFileTimeUnit -win $window]] / [unit_seconds [wvGetWindowTimeUnit -win $window]]}]
        wvZoom -win $window [expr {$start * $ratio}] [expr {$end * $ratio}]
        wvSetCursor -win $window [expr {$cursor * $ratio}]
    }
    wvRaiseWindow -win $window
    srcResizeWindow 0 0 1200 850
    srcRaiseWindow
} problem]} {
    set status [open [file join $output error.txt] w]
    puts $status $problem
    close $status
} else {
    set status [open [file join $output ready.txt] w]
    puts $status "Waveform loaded; signals=$signals; cursor=$cursor"
    close $status
}
