//! Expose digital vector bits through Surfer's native collapsed compound rows.
// SPDX-License-Identifier: EUPL-1.2

use surfer_translation_types::{
    SubFieldTranslationResult, TranslationResult, ValueKind, ValueRepr, VariableEncoding,
    VariableInfo, VariableMeta, VariableValue, extend_string, kind_for_binary_representation,
};

/// Return declared bit indices in packed-value order, including ascending/negative ranges.
fn bit_names<VarId, ScopeId>(variable: &VariableMeta<VarId, ScopeId>) -> Vec<String> {
    let width = variable.num_bits.unwrap_or(0);
    if variable.encoding != VariableEncoding::BitVector || width <= 1 {
        return vec![];
    }
    let (first, direction) = variable.index.map_or((i64::from(width) - 1, -1), |index| {
        (index.msb, if index.msb <= index.lsb { 1 } else { -1 })
    });
    (0..width)
        .map(|offset| {
            format!(
                "[{}]",
                i128::from(first) + i128::from(direction) * i128::from(offset)
            )
        })
        .collect()
}

/// Give flat digital vectors native bit children without changing scalar/structured types.
pub fn variable_info<VarId, ScopeId>(
    variable: &VariableMeta<VarId, ScopeId>,
    info: VariableInfo,
) -> VariableInfo {
    if !matches!(info, VariableInfo::Bits) {
        return info;
    }
    let names = bit_names(variable);
    if names.is_empty() {
        info
    } else {
        VariableInfo::Compound {
            subfields: names
                .into_iter()
                .map(|name| (name, VariableInfo::Bool))
                .collect(),
        }
    }
}

/// Add bit values while preserving the selected aggregate radix and unknown-state colors.
pub fn translate<VarId, ScopeId>(
    variable: &VariableMeta<VarId, ScopeId>,
    value: &VariableValue,
    result: &mut TranslationResult,
) {
    let names = bit_names(variable);
    if names.is_empty() || !result.subfields.is_empty() {
        return;
    }
    let width = variable.num_bits.unwrap_or(0);
    let bits = match value {
        VariableValue::BigUint(value) => format!("{value:0width$b}", width = width as usize),
        VariableValue::String(value) => {
            let value = value.to_ascii_lowercase();
            format!("{}{}", extend_string(&value, width), value)
        }
    };
    // Readers return one ASCII state per bit; malformed values get explicit error traces.
    let bits = if bits.len() == width as usize && bits.is_ascii() {
        bits
    } else {
        "?".repeat(width as usize)
    };
    result.subfields = names
        .into_iter()
        .zip(bits.bytes())
        .map(|(name, bit)| {
            let bit = char::from(bit);
            SubFieldTranslationResult {
                name,
                result: TranslationResult {
                    val: ValueRepr::Bit(bit),
                    kind: if matches!(bit, '0' | '1' | 'x' | 'z' | 'u' | 'w' | 'h' | 'l' | '-') {
                        kind_for_binary_representation(&bit.to_string())
                    } else {
                        ValueKind::Error
                    },
                    subfields: vec![],
                },
            }
        })
        .collect();
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use surfer_translation_types::{ScopeRef, VariableIndex, VariableRef};

    /// Construct source metadata independently of any waveform reader.
    fn metadata(width: u32, index: Option<(i64, i64)>) -> VariableMeta<(), ()> {
        VariableMeta {
            var: VariableRef {
                path: ScopeRef {
                    strs: vec![],
                    id: (),
                },
                name: "bus".into(),
                id: (),
                index: None,
            },
            num_bits: Some(width),
            variable_type: None,
            variable_type_name: None,
            index: index.map(|(msb, lsb)| VariableIndex { msb, lsb }),
            direction: None,
            enum_map: HashMap::new(),
            encoding: VariableEncoding::BitVector,
        }
    }

    #[test]
    /// Use declared indices rather than assuming every bus ends at zero.
    fn preserves_declared_bit_indices() {
        for (index, names) in [
            (None, vec!["[3]", "[2]", "[1]", "[0]"]),
            (Some((7, 4)), vec!["[7]", "[6]", "[5]", "[4]"]),
            (Some((0, 3)), vec!["[0]", "[1]", "[2]", "[3]"]),
            (Some((1, -2)), vec!["[1]", "[0]", "[-1]", "[-2]"]),
        ] {
            let variable = metadata(4, index);
            assert_eq!(bit_names(&variable), names);
            let VariableInfo::Compound { subfields } = variable_info(&variable, VariableInfo::Bits)
            else {
                panic!()
            };
            assert_eq!(subfields.len(), 4);
            assert!(
                subfields
                    .iter()
                    .all(|(_, info)| matches!(info, VariableInfo::Bool))
            );
        }
    }

    #[test]
    /// Preserve aggregate radix while mapping binary, zero-extension and X/Z to bits.
    fn preserves_aggregate_and_four_state_bits() {
        for (value, expected) in [
            (VariableValue::BigUint(5u32.into()), "0101"),
            (VariableValue::String("1".into()), "0001"),
            (VariableValue::String("X".into()), "xxxx"),
            (VariableValue::String("Z".into()), "zzzz"),
            (VariableValue::String("0x1z".into()), "0x1z"),
            (VariableValue::String("U".into()), "uuuu"),
            (VariableValue::String("W".into()), "wwww"),
            (VariableValue::String("H".into()), "hhhh"),
            (VariableValue::String("L".into()), "llll"),
            (VariableValue::String("-".into()), "----"),
            (VariableValue::String("?".into()), "????"),
            (VariableValue::String("10101".into()), "????"),
            (VariableValue::BigUint(16u32.into()), "????"),
        ] {
            let mut result = TranslationResult::single_string("aggregate", ValueKind::Normal);
            translate(&metadata(4, None), &value, &mut result);
            assert!(matches!(result.val, ValueRepr::String(ref value) if value == "aggregate"));
            let bits: String = result
                .subfields
                .iter()
                .map(|field| {
                    let ValueRepr::Bit(bit) = field.result.val else {
                        panic!()
                    };
                    if bit == 'x' {
                        assert!(matches!(field.result.kind, ValueKind::Undef));
                    }
                    if bit == 'z' {
                        assert!(matches!(field.result.kind, ValueKind::HighImp));
                    }
                    bit
                })
                .collect();
            assert_eq!(bits, expected);
        }
    }

    #[test]
    /// Keep wide vectors exact beyond JavaScript and machine integer precision.
    fn supports_wide_vectors() {
        let value = VariableValue::BigUint(num::BigUint::from(1u32) << 127usize);
        let mut result = TranslationResult::single_string("wide", ValueKind::Normal);
        translate(&metadata(128, None), &value, &mut result);
        assert_eq!(result.subfields.len(), 128);
        assert!(matches!(
            result.subfields[0].result.val,
            ValueRepr::Bit('1')
        ));
        assert!(matches!(
            result.subfields[127].result.val,
            ValueRepr::Bit('0')
        ));
    }

    #[test]
    /// Never turn clocks, reals, strings or existing structures into bit children.
    fn leaves_other_types_unchanged() {
        for width in [0, 1] {
            assert!(matches!(
                variable_info(&metadata(width, None), VariableInfo::Bits),
                VariableInfo::Bits
            ));
        }
        for encoding in [
            VariableEncoding::String,
            VariableEncoding::Real,
            VariableEncoding::Event,
        ] {
            let mut variable = metadata(32, None);
            variable.encoding = encoding;
            assert!(matches!(
                variable_info(&variable, VariableInfo::Bits),
                VariableInfo::Bits
            ));
        }
        assert!(matches!(
            variable_info(&metadata(4, None), VariableInfo::Clock),
            VariableInfo::Clock
        ));
        assert!(
            matches!(variable_info(&metadata(4, None), VariableInfo::Compound {subfields: vec![]}), VariableInfo::Compound {subfields} if subfields.is_empty())
        );
        let mut structured = TranslationResult::single_string("parent", ValueKind::Normal);
        structured.subfields.push(SubFieldTranslationResult {
            name: "existing".into(),
            result: TranslationResult::single_string("field", ValueKind::Normal),
        });
        translate(
            &metadata(4, None),
            &VariableValue::BigUint(5u32.into()),
            &mut structured,
        );
        assert_eq!(structured.subfields.len(), 1);
        assert_eq!(structured.subfields[0].name, "existing");
    }
}
