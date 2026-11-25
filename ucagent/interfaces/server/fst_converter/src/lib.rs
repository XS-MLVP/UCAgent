use fst_reader::{
    FstFilter, FstHierarchyEntry, FstReader, FstScopeType, FstSignalValue, FstVarType,
};
use std::alloc::{Layout, alloc, dealloc};
use std::fmt::Write as _;
use std::io::Cursor;
use std::sync::Mutex;

static RESULT: Mutex<Option<Vec<u8>>> = Mutex::new(None);
static ERROR: Mutex<Option<Vec<u8>>> = Mutex::new(None);

#[cfg(target_arch = "wasm32")]
#[link(wasm_import_module = "env")]
unsafe extern "C" {
    fn ucagent_report_progress(stage: i32, current: f64, total: f64);
}

#[derive(Clone, Copy)]
enum SignalKind {
    Bits(u32),
    Real,
    String,
}

#[unsafe(no_mangle)]
pub extern "C" fn ucagent_alloc(length: usize) -> *mut u8 {
    if length == 0 {
        return std::ptr::null_mut();
    }
    unsafe { alloc(Layout::array::<u8>(length).unwrap()) }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn ucagent_dealloc(pointer: *mut u8, capacity: usize) {
    if !pointer.is_null() && capacity != 0 {
        unsafe { dealloc(pointer, Layout::array::<u8>(capacity).unwrap()) };
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn ucagent_prepare_fst(pointer: *const u8, length: usize) -> i32 {
    clear_outputs();
    let input = if pointer.is_null() || length == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(pointer, length) }
    };
    match prepare_fst_bytes(input) {
        Ok(Some(vcd)) => {
            *RESULT.lock().unwrap() = Some(vcd);
            1
        }
        Ok(None) => 0,
        Err(error) => {
            *ERROR.lock().unwrap() = Some(error.into_bytes());
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn ucagent_result_ptr() -> *const u8 {
    RESULT
        .lock()
        .unwrap()
        .as_ref()
        .map_or(std::ptr::null(), |value| value.as_ptr())
}

#[unsafe(no_mangle)]
pub extern "C" fn ucagent_result_len() -> usize {
    RESULT.lock().unwrap().as_ref().map_or(0, Vec::len)
}

#[unsafe(no_mangle)]
pub extern "C" fn ucagent_error_ptr() -> *const u8 {
    ERROR
        .lock()
        .unwrap()
        .as_ref()
        .map_or(std::ptr::null(), |value| value.as_ptr())
}

#[unsafe(no_mangle)]
pub extern "C" fn ucagent_error_len() -> usize {
    ERROR.lock().unwrap().as_ref().map_or(0, Vec::len)
}

#[unsafe(no_mangle)]
pub extern "C" fn ucagent_clear_output() {
    clear_outputs();
}

fn clear_outputs() {
    *RESULT.lock().unwrap() = None;
    *ERROR.lock().unwrap() = None;
}

fn report_progress(stage: i32, current: u64, total: u64) {
    #[cfg(target_arch = "wasm32")]
    unsafe {
        ucagent_report_progress(stage, current as f64, total.max(1) as f64)
    };
    #[cfg(not(target_arch = "wasm32"))]
    let _ = (stage, current, total);
}

pub fn prepare_fst_bytes(input: &[u8]) -> Result<Option<Vec<u8>>, String> {
    report_progress(1, 0, 1);
    let mut reader = open_reader(input)?;
    let mut requires_fallback = false;
    reader
        .read_hierarchy(|entry| {
            if hierarchy_requires_fallback(&entry) {
                requires_fallback = true;
            }
        })
        .map_err(|error| format!("读取 FST hierarchy 失败：{error}"))?;
    report_progress(1, 1, 1);
    if !requires_fallback {
        return Ok(None);
    }
    convert_to_vcd(input).map(Some)
}

fn hierarchy_requires_fallback(entry: &FstHierarchyEntry) -> bool {
    matches!(
        entry,
        FstHierarchyEntry::Array { .. }
            | FstHierarchyEntry::SVEnum { .. }
            | FstHierarchyEntry::Pack { .. }
    )
}

fn open_reader(input: &[u8]) -> Result<FstReader<Cursor<&[u8]>>, String> {
    FstReader::open(Cursor::new(input)).map_err(|error| format!("打开 FST 失败：{error}"))
}

fn convert_to_vcd(input: &[u8]) -> Result<Vec<u8>, String> {
    let mut reader = open_reader(input)?;
    let header = reader.get_header();
    let mut output = String::with_capacity(input.len().saturating_mul(3));
    writeln!(output, "$date\n    {}\n$end", sanitize_text(&header.date)).unwrap();
    writeln!(
        output,
        "$version\n    UCAgent browser fallback ({})\n$end",
        sanitize_text(&header.version)
    )
    .unwrap();
    let (scale, unit) = vcd_timescale(header.timescale_exponent)?;
    writeln!(output, "$timescale {scale}{unit} $end").unwrap();

    let mut signal_kinds = vec![SignalKind::Bits(1); header.max_handle as usize];
    reader
        .read_hierarchy(|entry| match entry {
            FstHierarchyEntry::Scope { tpe, name, .. } => {
                writeln!(
                    output,
                    "$scope {} {} $end",
                    vcd_scope_type(tpe),
                    vcd_identifier(&name)
                )
                .unwrap();
            }
            FstHierarchyEntry::UpScope => {
                writeln!(output, "$upscope $end").unwrap();
            }
            FstHierarchyEntry::Var {
                tpe,
                name,
                length,
                handle,
                ..
            } => {
                let handle_index = handle.get_index();
                let kind = if tpe.is_real() {
                    SignalKind::Real
                } else if tpe == FstVarType::GenericString {
                    SignalKind::String
                } else {
                    SignalKind::Bits(length.max(1))
                };
                signal_kinds[handle_index] = kind;
                let (reference, range) = split_reference(&name, length);
                let range = range.map_or(String::new(), |value| format!(" {value}"));
                let var_type = match kind {
                    SignalKind::Real => "real",
                    SignalKind::String => "string",
                    SignalKind::Bits(_) => "wire",
                };
                writeln!(
                    output,
                    "$var {var_type} {} {} {}{} $end",
                    length.max(1),
                    vcd_id(handle_index),
                    vcd_identifier(reference),
                    range
                )
                .unwrap();
            }
            _ => {}
        })
        .map_err(|error| format!("转换 FST hierarchy 失败：{error}"))?;
    writeln!(output, "$enddefinitions $end").unwrap();

    let progress_span = header.end_time.saturating_sub(header.start_time).max(1);
    report_progress(2, 0, progress_span);
    let mut last_time = None;
    let mut last_progress = 0_u64;
    let progress_step = (progress_span / 100).max(1);
    reader
        .read_signals(&FstFilter::all(), |time, handle, value| {
            if last_time != Some(time) {
                writeln!(output, "#{time}").unwrap();
                last_time = Some(time);
            }
            let handle_index = handle.get_index();
            let id = vcd_id(handle_index);
            match (signal_kinds[handle_index], value) {
                (SignalKind::Real, FstSignalValue::Real(value)) => {
                    writeln!(output, "r{value} {id}").unwrap();
                }
                (SignalKind::String, FstSignalValue::String(value)) => {
                    let value = String::from_utf8_lossy(value);
                    writeln!(output, "s{} {id}", sanitize_value(&value)).unwrap();
                }
                (SignalKind::Bits(1), FstSignalValue::String(value)) => {
                    let bit = value.first().copied().map(normalize_bit).unwrap_or(b'x');
                    writeln!(output, "{}{id}", bit as char).unwrap();
                }
                (SignalKind::Bits(_), FstSignalValue::String(value)) => {
                    let normalized: String = value
                        .iter()
                        .map(|value| normalize_bit(*value) as char)
                        .collect();
                    writeln!(output, "b{normalized} {id}").unwrap();
                }
                (_, FstSignalValue::Real(value)) => {
                    writeln!(output, "r{value} {id}").unwrap();
                }
                (_, FstSignalValue::String(value)) => {
                    let value = String::from_utf8_lossy(value);
                    writeln!(output, "b{} {id}", sanitize_value(&value)).unwrap();
                }
            }
            let relative = time.saturating_sub(header.start_time);
            if relative.saturating_sub(last_progress) >= progress_step {
                report_progress(2, relative, progress_span);
                last_progress = relative;
            }
            Ok::<(), ()>(())
        })
        .map_err(|error| format!("转换 FST value changes 失败：{error}"))?;
    if last_progress < progress_span {
        report_progress(2, progress_span, progress_span);
    }
    Ok(output.into_bytes())
}

fn split_reference(name: &str, length: u32) -> (&str, Option<&str>) {
    let trimmed = name.trim();
    if length > 1
        && trimmed.ends_with(']')
        && let Some(position) = trimmed.rfind('[')
        && trimmed[position..].contains(':')
    {
        return (trimmed[..position].trim_end(), Some(&trimmed[position..]));
    }
    (trimmed, None)
}

fn vcd_id(mut index: usize) -> String {
    let mut value = String::new();
    loop {
        value.push(char::from_u32((index % 94 + 33) as u32).unwrap());
        index /= 94;
        if index == 0 {
            return value;
        }
    }
}

fn vcd_identifier(value: &str) -> String {
    let normalized: String = value
        .trim()
        .chars()
        .map(|character| {
            if character.is_ascii_whitespace() || character.is_control() {
                '_'
            } else {
                character
            }
        })
        .collect();
    if normalized.is_empty() {
        "unnamed".to_string()
    } else {
        normalized
    }
}

fn sanitize_text(value: &str) -> String {
    value
        .replace("$end", "end")
        .replace('\r', " ")
        .replace('\n', " ")
}

fn sanitize_value(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_whitespace() {
                '_'
            } else {
                character
            }
        })
        .collect()
}

fn normalize_bit(value: u8) -> u8 {
    match value.to_ascii_lowercase() {
        b'0' | b'l' => b'0',
        b'1' | b'h' => b'1',
        b'z' => b'z',
        _ => b'x',
    }
}

fn vcd_scope_type(scope_type: FstScopeType) -> &'static str {
    match scope_type {
        FstScopeType::Task => "task",
        FstScopeType::Function | FstScopeType::VhdlFunction => "function",
        FstScopeType::Begin => "begin",
        FstScopeType::Fork => "fork",
        _ => "module",
    }
}

fn vcd_timescale(exponent: i8) -> Result<(u32, &'static str), String> {
    if !(-15..=0).contains(&exponent) {
        return Err(format!(
            "FST timescale exponent {exponent} 无法表示为标准 VCD timescale"
        ));
    }
    let unit_exponent = exponent.div_euclid(3) * 3;
    let scale = match exponent - unit_exponent {
        0 => 1,
        1 => 10,
        _ => 100,
    };
    let unit = match unit_exponent {
        0 => "s",
        -3 => "ms",
        -6 => "us",
        -9 => "ns",
        -12 => "ps",
        -15 => "fs",
        _ => unreachable!(),
    };
    Ok((scale, unit))
}

#[cfg(test)]
mod tests {
    use super::*;
    use fst_reader::{FstArrayType, FstEnumType, FstPackType};

    #[test]
    fn unsupported_surfer_attributes_require_fallback() {
        assert!(hierarchy_requires_fallback(&FstHierarchyEntry::Array {
            name: "memory".to_string(),
            array_type: FstArrayType::Unpacked,
            left: 0,
            right: 15,
        }));
        assert!(hierarchy_requires_fallback(&FstHierarchyEntry::SVEnum {
            name: "state".to_string(),
            enum_type: FstEnumType::Logic,
            value: 1,
        }));
        assert!(hierarchy_requires_fallback(&FstHierarchyEntry::Pack {
            name: "packet".to_string(),
            pack_type: FstPackType::Packed,
            value: 1,
        }));
        assert!(!hierarchy_requires_fallback(&FstHierarchyEntry::Comment {
            string: "supported".to_string(),
        }));
    }

    #[test]
    fn vcd_ids_are_compact_and_deterministic() {
        assert_eq!(vcd_id(0), "!");
        assert_eq!(vcd_id(93), "~");
        assert_eq!(vcd_id(94), "!\"");
    }

    #[test]
    fn ranges_are_separated_from_vcd_references() {
        assert_eq!(split_reference("data [31:1]", 31), ("data", Some("[31:1]")));
        assert_eq!(
            split_reference("memory[3] [7:0]", 8),
            ("memory[3]", Some("[7:0]"))
        );
        assert_eq!(split_reference("memory[3]", 1), ("memory[3]", None));
    }

    #[test]
    fn timescales_preserve_decimal_exponents() {
        assert_eq!(vcd_timescale(-9).unwrap(), (1, "ns"));
        assert_eq!(vcd_timescale(-10).unwrap(), (100, "ps"));
        assert_eq!(vcd_timescale(-11).unwrap(), (10, "ps"));
        assert!(vcd_timescale(-16).is_err());
    }
}
