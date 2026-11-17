
# Test dependencies

The unit-test CI workflow installs UCAgent and pytest on Ubuntu with Python 3.11
and 3.12, sets up Node.js 22, then runs `make unitytest`. The Python command
includes `-ra` so skipped-test reasons appear in the CI log.

Install the project dependencies before running tests. Missing required Python
dependencies remain installation errors. Optional external runtimes are checked
before the tests that need them and produce a skip when unavailable:

| Tests | Optional prerequisites |
| --- | --- |
| Real Xpra runtime | Linux, working Xpra, Xvfb and xpra-html5 assets |
| Full CLI/Xpra runtime | Also picker, Verilator, CMake, Make, a C++ compiler, SWIG, xterm, xclock and Bash |
| Graphical waveform runtime | Also Tk in the Python interpreter running pytest |
| Browser acceptance | Playwright, the requested browser executable and its native libraries; Xpra browser tests also need the external server URL and password |
| Coverage provider integration | Toffee's `code_coverage` and VCS provider modules; these tests use a session substitute and do not require Verdi |
| Live USDB queries | Configured UVS simulator plus working `usdbaccess` and `dap` in the UVS/UVD installations |
| Built documentation | All themes, extensions and plugins from `docs/requirements-docs.txt`; PDF checks also need Pandoc |
| Make integration | Make; the Swarm recipe tests substitute Docker, HTTP and the clock |

Real runtime and browser tests retain their opt-in environment variables listed
in each test module. Opting in does not bypass dependency checks. Xpra HTML5
resources are checked under the installation prefixes; for a custom resource
root, set Xpra's `XPRA_RESOURCES_DIR` to the directory containing `www/index.html`.

The normal API and Xpra lifecycle tests use isolated executable/session
substitutes and continue to run without a real Xpra server. Missing-tool and
error-diagnostic unit tests also continue to run. Once preflight succeeds,
application assertions and unexpected runtime failures must fail the test;
they must not be converted into skips.
