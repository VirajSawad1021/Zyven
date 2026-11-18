# Mutation test of the gates (2026-11-18)

**80/96 mutants killed (83%)** across graph_algorithms, hijri_gregorian_conversion, iban_validation, isbn_ean_validation, jewish_holidays_and_fasts; seed 1; upstream-tests gate skipped (it tests the library, not the adapter); 20 min.

| Gate | First to fail | Failed at all |
|---|---|---|
| differential | 27 | 74 |
| mcp_smoke | 52 | 52 |
| input_robustness | 1 | 1 |

"Failed at all" counts every gate that failed for a mutant. Policy and import failures stop verification, so later gates did not run for those.

| Operator | Killed / total |
|---|---|
| arithmetic | 1/1 |
| boolean | 1/3 |
| compare | 4/5 |
| drop_return_field | 6/9 |
| drop_statement | 33/35 |
| flip_bool | 6/9 |
| negate_condition | 9/11 |
| off_by_one | 7/9 |
| swap_args | 13/14 |

## Survivors (a gap in the gates, or an equivalent mutant: read each)

- `graph_algorithms.shortest_path_weight` swap_args: line 14: first two arguments swapped
- `graph_algorithms.highest_betweenness_centrality_node` negate_condition: line 5: condition negated
- `graph_algorithms.highest_betweenness_centrality_node` compare: line 5: NotEq -> Eq
- `graph_algorithms.highest_betweenness_centrality_node` off_by_one: line 5: 3 -> 4
- `graph_algorithms.count_triangles` negate_condition: line 7: condition negated
- `hijri_gregorian_conversion.convert_gregorian_to_hijri` boolean: line 7: And -> Or
- `hijri_gregorian_conversion.get_hijri_date_info` boolean: line 4: And -> Or
- `isbn_ean_validation.validate_and_format_isbn` drop_return_field: line 38: return field 'error' dropped
- `isbn_ean_validation.validate_and_format_isbn` flip_bool: line 39: False -> True
- `isbn_ean_validation.validate_and_format_ean` flip_bool: line 26: False -> True
- `isbn_ean_validation.validate_and_format_ean` drop_return_field: line 25: return field 'error' dropped
- `jewish_holidays_and_fasts.get_jewish_festival` flip_bool: line 26: False -> True
- `jewish_holidays_and_fasts.get_jewish_festival` drop_statement: line 26: statement dropped: israel = bool(israel) if israel is not None else False
- `iban_validation.validate_iban` drop_return_field: line 10: return field 'formatted_iban' dropped
- `iban_validation.calculate_iban_check_digits` off_by_one: line 18: 4 -> 5
- `iban_validation.calculate_iban_check_digits` drop_statement: line 22: statement dropped: new_compact_iban = new_compact_iban.upper()
