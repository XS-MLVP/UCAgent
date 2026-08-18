# Browser FST fallback converter

This crate builds the WebAssembly module used by the bundled Surfer page when
the current Surfer FST reader cannot handle ARRAY, ENUM, or PACK hierarchy
attributes. It does not replace Surfer and compatible FST files are not
converted. Conversion runs in a browser Web Worker; only converted VCD data is
persisted in the browser cache.

Build the checked-in browser artifact with:

```bash
rustup target add wasm32-unknown-unknown
CARGO_TARGET_DIR=/tmp/ucagent-fst-converter-target \
  cargo build --manifest-path ucagent/server/fst_converter/Cargo.toml \
  --release --target wasm32-unknown-unknown
cp /tmp/ucagent-fst-converter-target/wasm32-unknown-unknown/release/ucagent_fst_converter.wasm \
  ucagent/server/static/surfer/fst-converter.wasm
```

When conversion behavior changes, update the matching converter version in
`fst-fallback.js` and `fst-fallback-worker.js` so existing browser cache entries
cannot be mistaken for output from the new converter.

The converter uses `fst-reader`, distributed under the BSD-3-Clause license.
