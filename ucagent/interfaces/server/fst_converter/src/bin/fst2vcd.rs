use std::path::PathBuf;

fn main() -> Result<(), String> {
    let source = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or_else(|| "missing source FST path".to_string())?;
    let target = std::env::args_os()
        .nth(2)
        .map(PathBuf::from)
        .ok_or_else(|| "missing target VCD path".to_string())?;
    let input = std::fs::read(&source)
        .map_err(|error| format!("failed to read {}: {error}", source.display()))?;
    let output = ucagent_fst_converter::prepare_fst_bytes(&input)?
        .ok_or_else(|| "the FST is compatible and does not require conversion".to_string())?;
    std::fs::write(&target, output)
        .map_err(|error| format!("failed to write {}: {error}", target.display()))
}
