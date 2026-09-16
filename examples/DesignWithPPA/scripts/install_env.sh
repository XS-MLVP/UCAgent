#!/usr/bin/env bash
#
# Download and install the external toolchain required by the DesignWithPPA
# plugin, pinned to the versions documented in examples/DesignWithPPA/README.md
# and the plugin's Chisel contract in src/design_with_ppa/rtl.py:
#
#   yosys     v0.68                    source build (needs CMake >= 3.28)
#   OpenSTA   >= 3.1.0                 source build from the repository's
#                                       default branch (CMake project version
#                                       is 3.1.0); installs the `sta` binary
#   JDK 17    Temurin 17 (latest GA)   installed to
#                                       ~/.local/share/ucagent-toolchains/jdk-17
#                                       (the default CHISEL_JAVA_HOME of the
#                                       plugin Makefile)
#   Mill      0.4.2                    installed to ~/.local/bin/mill
#   Chisel    7.15.0 / Scala 2.13.18   resolved by Mill into its coursier
#                                       cache during the warm-up step
#   picker    optional (--with-picker) built from source; requires
#                                       Verilator >= 5.020 (installed or built
#                                       automatically when needed)
#
# Supported platforms: Ubuntu/Debian hosts using apt, and macOS hosts using
# Homebrew. Standard http_proxy/https_proxy/no_proxy environment variables are
# honored by curl, git, and Mill.
#
# Usage:
#   bash scripts/install_env.sh [options]
#
# Options:
#   --prefix DIR           installation prefix for yosys/OpenSTA/verilator
#                          (default: /usr/local; apt packages still need sudo)
#   --with-picker          also install picker and a Verilator >= 5.020
#   --skip-yosys           do not install yosys
#   --skip-opensta         do not install OpenSTA
#   --skip-chisel          do not install the JDK 17 + Mill 0.4.2 toolchain
#   --skip-chisel-warmup   do not pre-resolve Chisel/Scala artifacts with Mill
#   --force                reinstall components even when versions already match
#   --jobs N               parallel build jobs (default: all CPU cores)
#   -h, --help             show this help
#
# Examples:
#   bash scripts/install_env.sh
#   bash scripts/install_env.sh --with-picker
#   bash scripts/install_env.sh --prefix "$HOME/.local" --skip-chisel
#
# Already-satisfying installations are detected and skipped. After the run,
# make sure <prefix>/bin and ~/.local/bin are on PATH and verify with:
#   make check-deps

set -euo pipefail

# Component versions; keep in sync with README.md and src/design_with_ppa/rtl.py.
YOSYS_VERSION="0.68"
OPENSTA_REPO_URL="https://github.com/The-OpenROAD-Project/OpenSTA.git"
OPENSTA_MIN_VERSION="3.1.0"
CHISEL_VERSION="7.15.0"
CHISEL_SCALA_VERSION="2.13.18"
MILL_VERSION="0.4.2"
JDK_MAJOR_VERSION="17"
VERILATOR_MIN_VERSION="5.020"
SWIG_MIN_VERSION="4.1"
SWIG_FALLBACK_VERSION="4.3.0"

TOOLCHAIN_ROOT="${HOME}/.local/share/ucagent-toolchains"
JDK_HOME="${TOOLCHAIN_ROOT}/jdk-${JDK_MAJOR_VERSION}"
USER_BIN_DIR="${HOME}/.local/bin"

PREFIX="/usr/local"
WITH_PICKER=0
SKIP_YOSYS=0
SKIP_OPENSTA=0
SKIP_CHISEL=0
SKIP_WARMUP=0
FORCE=0
JOBS=""
PLATFORM=""
WORK_DIR=""
APT_UPDATED=0

log() { printf '==> %s\n' "$*"; }
step() { printf '    %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

# Succeed when dotted version HAVE >= WANT ("1.8" >= "0.68", "3.2" >= "3.1.0").
version_ge() {
    awk -v hv="$1" -v wv="$2" 'BEGIN {
        n = split(hv, h, "."); m = split(wv, w, ".");
        if (m > n) n = m;
        for (i = 1; i <= n; i++) {
            a = (h[i] == "") ? 0 : h[i] + 0;
            b = (w[i] == "") ? 0 : w[i] + 0;
            if (a != b) exit (a < b);
        }
        exit 0;
    }'
}

# Print the first dotted number found in the given text.
tool_version() {
    printf '%s\n' "$1" | grep -oE '[0-9]+(\.[0-9]+)+' | head -n 1
}

try_fetch() { # try_fetch URL OUTPUT: download with retries, report failure
    local i
    for i in 1 2 3; do
        curl -fL -C - --connect-timeout 20 --retry 3 -o "$2" "$1" && return 0
        sleep 3
    done
    return 1
}

fetch() { # fetch URL OUTPUT: download or abort
    try_fetch "$1" "$2" || die "download failed: $1"
}

github_api() { # github_api ENDPOINT: print the JSON body
    local i
    for i in 1 2 3; do
        curl -fsSL --connect-timeout 20 "https://api.github.com$1" && return 0
        sleep 3
    done
    return 1
}

run_root() { # run_root CMD...: run through sudo unless already root
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

prefix_is_writable() {
    [ -w "${PREFIX}" ] || [ "$(id -u)" -eq 0 ]
}

# Install a configured CMake build tree into PREFIX, using sudo when needed.
cmake_install() { # cmake_install BUILD_DIR
    local cmake_bin
    cmake_bin=$(command -v cmake)
    if prefix_is_writable; then
        "${cmake_bin}" --install "$1"
    else
        run_root "${cmake_bin}" --install "$1"
    fi
}

make_install() { # make_install [MAKE ARGS...]
    local make_bin
    make_bin=$(command -v make)
    if prefix_is_writable; then
        "${make_bin}" "$@"
    else
        run_root "${make_bin}" "$@"
    fi
}

apt_install() { # apt_install PKG...
    if [ "${APT_UPDATED}" -eq 0 ]; then
        run_root apt-get update
        APT_UPDATED=1
    fi
    run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

brew_install() { # brew_install FORMULA...
    local missing=() formula
    for formula in "$@"; do
        brew list --versions "${formula}" >/dev/null 2>&1 || missing+=("${formula}")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        brew install "${missing[@]}"
    fi
}

# Make sure cmake >= WANT is available; upgrades via brew (macOS) or via
# snap/pip fallbacks (Ubuntu 22.04 ships cmake 3.22, too old for yosys 0.68).
ensure_cmake() { # ensure_cmake WANT
    local have=""
    if command -v cmake >/dev/null 2>&1; then
        have=$(tool_version "$(cmake --version 2>&1 | head -n 1)")
    fi
    version_ge "${have}" "$1" && return 0
    step "upgrading cmake (found ${have:-none}, need >= $1)"
    case "${PLATFORM}" in
        macos)
            brew_install cmake
            ;;
        linux)
            if command -v snap >/dev/null 2>&1 && [ -d /snap ]; then
                if run_root snap install cmake --classic >/dev/null 2>&1; then
                    PATH="/snap/bin:${PATH}"
                fi
            fi
            have=$(tool_version "$(cmake --version 2>&1 | head -n 1 || true)")
            if ! version_ge "${have}" "$1"; then
                apt_install python3-pip
                python3 -m pip install --user cmake \
                    || python3 -m pip install --user --break-system-packages cmake
                PATH="${USER_BIN_DIR}:${PATH}"
            fi
            ;;
    esac
    have=$(tool_version "$(cmake --version 2>&1 | head -n 1)")
    version_ge "${have}" "$1" || die "cmake >= $1 is required but ${have:-none} was found"
}

# Ubuntu 22.04 ships swig 4.0 while OpenSTA requires >= 4.1; build a newer one.
build_swig() { # build_swig VERSION
    local version="$1" src="${WORK_DIR}/swig-${version}"
    step "building swig ${version} from source"
    apt_install libpcre3-dev
    fetch "https://github.com/swig/swig/releases/download/v${version}/swig-${version}.tar.gz" \
        "${WORK_DIR}/swig-${version}.tar.gz"
    mkdir -p "${src}"
    tar -xzf "${WORK_DIR}/swig-${version}.tar.gz" -C "${src}" --strip-components=1
    (
        cd "${src}"
        ./configure --prefix="${PREFIX}" || ./configure --prefix="${PREFIX}" --without-pcre
        make -j "${JOBS}"
        make_install install
    )
    hash -r
}

existing_yosys_ok() {
    command -v yosys >/dev/null 2>&1 || return 1
    local have
    have=$(tool_version "$(yosys -V 2>&1 || true)")
    [ -n "${have}" ] && version_ge "${have}" "${YOSYS_VERSION}"
}

install_yosys() {
    log "yosys v${YOSYS_VERSION} (source build)"
    if [ "${FORCE}" -eq 0 ] && existing_yosys_ok; then
        step "already installed: $(yosys -V 2>&1 | head -n 1) -> skip"
        return 0
    fi
    local extra_args=""
    case "${PLATFORM}" in
        linux)
            apt_install git build-essential pkg-config python3 gawk make \
                bison flex libffi-dev libfl-dev libreadline-dev tcl-dev \
                zlib1g-dev
            ensure_cmake "3.28"
            local gcc_major
            gcc_major=$(gcc -dumpversion 2>/dev/null | cut -d. -f1 || echo 0)
            if [ "${gcc_major}" -lt 12 ]; then
                # gcc 11 has incomplete C++20 support; yosys 0.68 needs C++20.
                apt_install clang
                extra_args="-DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++"
            fi
            ;;
        macos)
            brew_install bison flex gawk readline libffi pkg-config tcl-tk zlib
            ensure_cmake "3.28"
            # brew bison is keg-only and must win over the ancient Xcode one.
            PATH="$(brew --prefix bison)/bin:$(brew --prefix flex)/bin:${PATH}"
            extra_args="-DCMAKE_PREFIX_PATH=$(brew --prefix tcl-tk):$(brew --prefix zlib):$(brew --prefix readline):$(brew --prefix libffi)"
            ;;
    esac
    local src="${WORK_DIR}/yosys-${YOSYS_VERSION}"
    step "downloading https://github.com/YosysHQ/yosys/releases/download/v${YOSYS_VERSION}/yosys.tar.gz"
    fetch "https://github.com/YosysHQ/yosys/releases/download/v${YOSYS_VERSION}/yosys.tar.gz" \
        "${WORK_DIR}/yosys.tar.gz"
    mkdir -p "${src}"
    tar -xzf "${WORK_DIR}/yosys.tar.gz" -C "${src}" --strip-components=1
    (
        cd "${src}"
        # shellcheck disable=SC2086
        cmake -B build -S . -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_INSTALL_PREFIX="${PREFIX}" ${extra_args}
        cmake --build build --parallel "${JOBS}"
        cmake_install build
    )
    hash -r
    "${PREFIX}/bin/yosys" -V 2>&1 | head -n 1 | grep -q "Yosys ${YOSYS_VERSION}" \
        || die "yosys ${YOSYS_VERSION} verification failed at ${PREFIX}/bin/yosys"
    step "installed: $("${PREFIX}/bin/yosys" -V 2>&1 | head -n 1)"
}

OPENSTA_CMD=""

existing_opensta_ok() {
    local name have
    for name in sta opensta; do
        command -v "${name}" >/dev/null 2>&1 || continue
        have=$(tool_version "$("${name}" -version 2>&1 || true)")
        if [ -n "${have}" ] && version_ge "${have}" "${OPENSTA_MIN_VERSION}"; then
            OPENSTA_CMD="${name}"
            return 0
        fi
    done
    return 1
}

install_opensta() {
    log "OpenSTA >= ${OPENSTA_MIN_VERSION} (source build)"
    if [ "${FORCE}" -eq 0 ] && existing_opensta_ok; then
        step "already installed: ${OPENSTA_CMD} $("${OPENSTA_CMD}" -version 2>&1 | head -n 1) at $(command -v "${OPENSTA_CMD}") -> skip"
        return 0
    fi
    local extra_args=""
    case "${PLATFORM}" in
        linux)
            apt_install git build-essential cmake tcl-dev swig bison flex \
                libeigen3-dev zlib1g-dev
            ensure_cmake "3.24"
            local swig_have
            swig_have=$(tool_version "$(swig -version 2>&1 || true)")
            if ! version_ge "${swig_have}" "${SWIG_MIN_VERSION}"; then
                build_swig "${SWIG_FALLBACK_VERSION}"
            fi
            ;;
        macos)
            brew_install swig bison flex eigen tcl-tk zlib
            ensure_cmake "3.24"
            PATH="$(brew --prefix bison)/bin:$(brew --prefix flex)/bin:${PATH}"
            extra_args="-DCMAKE_PREFIX_PATH=$(brew --prefix tcl-tk):$(brew --prefix zlib):$(brew --prefix eigen)"
            ;;
    esac
    local src="${WORK_DIR}/OpenSTA"
    step "cloning ${OPENSTA_REPO_URL} (default branch, CMake project version ${OPENSTA_MIN_VERSION})"
    git clone --depth 1 "${OPENSTA_REPO_URL}" "${src}"
    local project_version
    project_version=$(sed -n 's/^project(STA VERSION \([0-9.]*\).*/\1/p' "${src}/CMakeLists.txt" | head -n 1)
    step "building OpenSTA ${project_version:-unknown}"
    (
        cd "${src}"
        # shellcheck disable=SC2086
        cmake -B build -S . -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_INSTALL_PREFIX="${PREFIX}" ${extra_args}
        cmake --build build --parallel "${JOBS}"
        cmake_install build
    )
    hash -r
    local sta_version
    sta_version=$(tool_version "$("${PREFIX}/bin/sta" -version 2>&1 || true)")
    [ -n "${sta_version}" ] || die "OpenSTA verification failed at ${PREFIX}/bin/sta"
    version_ge "${sta_version}" "${OPENSTA_MIN_VERSION}" \
        || die "OpenSTA ${sta_version} < required ${OPENSTA_MIN_VERSION}"
    step "installed: sta ${sta_version} at ${PREFIX}/bin/sta"
}

java_major_of() { # java_major_of JAVA_EXECUTABLE
    local out
    out="$("$1" -version 2>&1 || true)"
    printf '%s\n' "${out}" \
        | sed -n 's/.*version "\([0-9][0-9]*\)[."].*/\1/p' | head -n 1
}

install_jdk17() {
    log "Eclipse Temurin JDK ${JDK_MAJOR_VERSION} -> ${JDK_HOME}"
    local java_bin="${JDK_HOME}/bin/java" major
    if [ "${FORCE}" -eq 0 ] && [ -x "${java_bin}" ]; then
        major=$(java_major_of "${java_bin}")
        if [ -n "${major}" ] && [ "${major}" -ge "${JDK_MAJOR_VERSION}" ]; then
            step "already installed: $("${java_bin}" -version 2>&1 | head -n 1) -> skip"
            return 0
        fi
    fi
    local os arch archive asset_url extract_dir inner
    case "$(uname -s)" in Darwin) os="mac" ;; *) os="linux" ;; esac
    case "$(uname -m)" in
        x86_64) arch="x64" ;;
        arm64 | aarch64) arch="aarch64" ;;
        *) die "unsupported architecture $(uname -m) for the JDK download" ;;
    esac
    archive="${WORK_DIR}/jdk17-${os}-${arch}.tar.gz"
    step "downloading Temurin ${JDK_MAJOR_VERSION} GA (${os}/${arch})"
    if ! try_fetch \
        "https://api.adoptium.net/v3/binary/latest/${JDK_MAJOR_VERSION}/ga/${os}/${arch}/jdk/hotspot/normal/eclipse" \
        "${archive}"; then
        warn "Adoptium API unreachable; falling back to GitHub release assets"
        asset_url=$(github_api "/repos/adoptium/temurin17-binaries/releases/latest" \
            | grep -oE "https://[^\"]+/OpenJDK17U-jdk_${arch}_${os}_hotspot_[^\"]+\.tar\.gz" \
            | grep -v sbom | head -n 1 || true)
        [ -n "${asset_url}" ] || die "could not locate a Temurin ${JDK_MAJOR_VERSION} tarball for ${os}/${arch}"
        fetch "${asset_url}" "${archive}"
    fi
    extract_dir="${WORK_DIR}/jdk17-extract"
    mkdir -p "${extract_dir}"
    tar -xzf "${archive}" -C "${extract_dir}"
    inner=$(find "${extract_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    [ -n "${inner}" ] || die "unexpected JDK archive layout"
    if [ "${PLATFORM}" = "macos" ] && [ -d "${inner}/Contents/Home" ]; then
        inner="${inner}/Contents/Home"
    fi
    rm -rf "${JDK_HOME}"
    mkdir -p "$(dirname "${JDK_HOME}")"
    mv "${inner}" "${JDK_HOME}"
    major=$(java_major_of "${JDK_HOME}/bin/java")
    [ -n "${major}" ] && [ "${major}" -ge "${JDK_MAJOR_VERSION}" ] \
        || die "installed JDK reports version ${major:-unknown} at ${JDK_HOME}"
    step "installed: $("${JDK_HOME}/bin/java" -version 2>&1 | head -n 1)"
}

# The classic Mill launcher must report exactly the pinned version on its own
# line, mirroring the check performed by the plugin and `make chisel-toolchain`.
mill_reports_pinned_version() { # mill_reports_pinned_version MILL_PATH
    local out tmp
    tmp=$(mktemp -d "${TMPDIR:-/tmp}/ucagent-mill.XXXXXX")
    out=$(cd "${tmp}" \
        && JAVA_HOME="${JDK_HOME}" PATH="${JDK_HOME}/bin:${PATH}" sh "$1" -i version 2>&1 \
        || true)
    rm -rf "${tmp}"
    printf '%s\n' "${out}" | grep -qxE "[[:space:]]*${MILL_VERSION}[[:space:]]*"
}

install_mill() {
    log "Mill ${MILL_VERSION} -> ${USER_BIN_DIR}/mill"
    local target="${USER_BIN_DIR}/mill"
    if [ "${FORCE}" -eq 0 ] && [ -x "${target}" ] \
        && mill_reports_pinned_version "${target}"; then
        step "already installed: mill ${MILL_VERSION} -> skip"
        return 0
    fi
    mkdir -p "${USER_BIN_DIR}"
    fetch "https://github.com/com-lihaoyi/mill/releases/download/${MILL_VERSION}/${MILL_VERSION}" \
        "${target}"
    chmod +x "${target}"
    mill_reports_pinned_version "${target}" \
        || die "mill ${MILL_VERSION} verification failed at ${target}"
    local resolved
    resolved=$(command -v mill || true)
    [ "${resolved}" = "${target}" ] \
        || warn "another mill at ${resolved} shadows ${target}; keep ${USER_BIN_DIR} first on PATH"
    step "installed: mill ${MILL_VERSION} at ${target}"
}

# Pre-resolve Chisel/Scala artifacts with the same private Mill project the
# plugin renders at runtime, so the first workflow run stays offline for setup.
warm_chisel_dependencies() {
    if [ "${SKIP_WARMUP}" -eq 1 ]; then
        step "Chisel warm-up skipped by option"
        return 0
    fi
    log "resolving Chisel ${CHISEL_VERSION} / Scala ${CHISEL_SCALA_VERSION} with Mill"
    local project="${WORK_DIR}/chisel-warmup"
    mkdir -p "${project}/design/src"
    touch "${project}/design/src/.keep"
    cat > "${project}/build.sc" <<EOF
import mill._, scalalib._

object design extends ScalaModule {
  def scalaVersion = "${CHISEL_SCALA_VERSION}"
  def ivyDeps = Agg(ivy"org.chipsalliance::chisel:${CHISEL_VERSION}")
  def scalacPluginIvyDeps = Agg(ivy"org.chipsalliance:::chisel-plugin:${CHISEL_VERSION}")
  def scalacOptions = Seq(
    "-deprecation",
    "-feature",
    "-unchecked",
    "-language:reflectiveCalls",
    "-Xcheckinit",
    "-Ymacro-annotations"
  )
}
EOF
    if (cd "${project}" \
        && JAVA_HOME="${JDK_HOME}" PATH="${JDK_HOME}/bin:${PATH}" \
            sh "${USER_BIN_DIR}/mill" -i design.compile); then
        step "Chisel ${CHISEL_VERSION} (Scala ${CHISEL_SCALA_VERSION}) resolved into the Mill cache"
    else
        warn "Chisel warm-up failed; Mill will retry the download on the first workflow run"
    fi
}

existing_verilator_ok() {
    command -v verilator >/dev/null 2>&1 || return 1
    local have
    have=$(tool_version "$(verilator --version 2>&1 || true)")
    [ -n "${have}" ] && version_ge "${have}" "${VERILATOR_MIN_VERSION}"
}

ensure_verilator() {
    if existing_verilator_ok; then
        step "verilator $(verilator --version 2>&1 | head -n 1) satisfies >= ${VERILATOR_MIN_VERSION}"
        return 0
    fi
    local have
    have=$(tool_version "$(verilator --version 2>&1 || true)")
    step "verilator ${have:-none} < ${VERILATOR_MIN_VERSION}; installing"
    case "${PLATFORM}" in
        linux)
            apt_install verilator
            if existing_verilator_ok; then return 0; fi
            step "building verilator ${VERILATOR_MIN_VERSION} from source"
            apt_install git make autoconf g++ flex bison libfl-dev zlib1g-dev \
                perl python3 ccache
            local src="${WORK_DIR}/verilator"
            git clone --depth 1 --branch "v${VERILATOR_MIN_VERSION}" \
                https://github.com/verilator/verilator.git "${src}"
            (
                cd "${src}"
                autoconf
                ./configure --prefix="${PREFIX}"
                make -j "${JOBS}"
                make_install install
            )
            hash -r
            ;;
        macos)
            brew_install verilator
            ;;
    esac
    existing_verilator_ok \
        || die "verilator >= ${VERILATOR_MIN_VERSION} is required by picker but is unavailable"
}

existing_picker_ok() {
    command -v picker >/dev/null 2>&1 || return 1
    picker export --help >/dev/null 2>&1
}

install_picker() {
    log "picker (source build, optional workflow dependency)"
    if [ "${FORCE}" -eq 0 ] && existing_picker_ok; then
        step "already installed: $(command -v picker) -> skip"
        return 0
    fi
    ensure_verilator
    local src="${WORK_DIR}/picker"
    step "cloning https://github.com/XS-MLVP/picker.git (default branch)"
    git clone --depth 1 https://github.com/XS-MLVP/picker.git "${src}"
    (
        cd "${src}"
        make init
        make
        if prefix_is_writable; then
            make install ARGS="-DCMAKE_INSTALL_PREFIX=${PREFIX}"
        else
            run_root env PATH="${PATH}" make install ARGS="-DCMAKE_INSTALL_PREFIX=${PREFIX}"
        fi
    )
    hash -r
    existing_picker_ok || die "picker verification failed after installation"
    step "installed: $(command -v picker)"
}

print_summary() {
    log "summary"
    command -v yosys >/dev/null 2>&1 \
        && step "yosys:    $(yosys -V 2>&1 | head -n 1)"
    command -v sta >/dev/null 2>&1 \
        && step "OpenSTA:  sta $(sta -version 2>&1 | head -n 1)"
    [ -x "${JDK_HOME}/bin/java" ] \
        && step "JDK:      $("${JDK_HOME}/bin/java" -version 2>&1 | head -n 1)"
    command -v mill >/dev/null 2>&1 \
        && step "mill:     $(command -v mill)"
    if [ "${WITH_PICKER}" -eq 1 ]; then
        command -v picker >/dev/null 2>&1 \
            && step "picker:   $(command -v picker)"
    fi
    echo
    echo "PATH reminders:"
    case ":${PATH}:" in
        *":${PREFIX}/bin:"*) : ;;
        *) echo "  export PATH=\"${PREFIX}/bin:\$PATH\"" ;;
    esac
    case ":${PATH}:" in
        *":${USER_BIN_DIR}:"*) : ;;
        *) echo "  export PATH=\"${USER_BIN_DIR}:\$PATH\"" ;;
    esac
    echo "Verify the plugin environment with: make check-deps"
    echo "Chisel mode uses CHISEL_JAVA_HOME=${JDK_HOME} (the Makefile default)."
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --prefix)
                [ "$#" -ge 2 ] || die "--prefix requires a directory argument"
                PREFIX="$2"
                shift 2
                ;;
            --with-picker) WITH_PICKER=1; shift ;;
            --skip-yosys) SKIP_YOSYS=1; shift ;;
            --skip-opensta) SKIP_OPENSTA=1; shift ;;
            --skip-chisel) SKIP_CHISEL=1; shift ;;
            --skip-chisel-warmup) SKIP_WARMUP=1; shift ;;
            --force) FORCE=1; shift ;;
            --jobs)
                [ "$#" -ge 2 ] || die "--jobs requires a numeric argument"
                printf '%s' "$2" | grep -qE '^[1-9][0-9]*$' \
                    || die "--jobs requires a positive integer: $2"
                JOBS="$2"
                shift 2
                ;;
            -h | --help) usage; exit 0 ;;
            *) die "unknown option: $1 (see --help)" ;;
        esac
    done
    case "${PREFIX}" in
        /*) : ;;
        *) die "--prefix must be an absolute path: ${PREFIX}" ;;
    esac
}

detect_platform() {
    case "$(uname -s)" in
        Darwin)
            command -v brew >/dev/null 2>&1 \
                || die "Homebrew is required on macOS: https://brew.sh"
            PLATFORM="macos"
            ;;
        Linux)
            command -v apt-get >/dev/null 2>&1 \
                || die "only apt-based Linux distributions are supported"
            PLATFORM="linux"
            ;;
        *)
            die "unsupported platform: $(uname -s) (supported: Ubuntu/Debian, macOS)"
            ;;
    esac
    if [ -z "${JOBS}" ]; then
        if command -v nproc >/dev/null 2>&1; then
            JOBS=$(nproc)
        else
            JOBS=$(sysctl -n hw.ncpu)
        fi
    fi
}

install_base_deps() {
    case "${PLATFORM}" in
        linux)
            apt_install ca-certificates curl git build-essential pkg-config python3
            ;;
        macos)
            command -v clang >/dev/null 2>&1 \
                || die "Xcode Command Line Tools are required: xcode-select --install"
            ;;
    esac
}

main() {
    parse_args "$@"
    detect_platform
    WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ucagent-designwithppa-env.XXXXXX")
    trap 'if [ -n "${WORK_DIR:-}" ]; then rm -rf "${WORK_DIR}"; fi' EXIT INT TERM
    # Tools installed by earlier steps must be discoverable by later ones.
    PATH="${PREFIX}/bin:${USER_BIN_DIR}:${PATH}"
    export PATH

    log "DesignWithPPA environment installer (platform: ${PLATFORM}, jobs: ${JOBS}, prefix: ${PREFIX})"
    install_base_deps
    [ "${SKIP_YOSYS}" -eq 1 ] || install_yosys
    [ "${SKIP_OPENSTA}" -eq 1 ] || install_opensta
    if [ "${SKIP_CHISEL}" -eq 0 ]; then
        install_jdk17
        install_mill
        warm_chisel_dependencies
    fi
    [ "${WITH_PICKER}" -eq 1 ] && install_picker
    print_summary
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
