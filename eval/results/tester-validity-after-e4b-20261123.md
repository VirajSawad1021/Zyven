# Tester validity: after-e4b (2026-11-23)

- **Model:** `gemma4:e4b@kaggle-t4-ollama`
- **Code:** commit `ad478c2`
- **Valid** means the reference program evaluates in the sandbox on its own case's arguments; whether it
  matches a tool is not measured. Specs are frozen (`eval/tester_specs/`), so only the Tester varies.
- Each cell is the mean over runs, with the range when runs differ.

| Library | Capability | Runs | (a) valid, Tester's answer | (b) valid, after re-ask | (c) tools with a valid case |
|---|---|---|---|---|---|
| hijridate | hijri_gregorian_conversion | 3 | 45% (0% to 73%) | 50% (10% to 73%) | 1.7 (1 to 2) of 3 |
| networkx | graph_algorithms | 3 | 0% | 0% | 0.0 of 6 |
| packaging | version_specifiers | 3 | 96% (90% to 100%) | 97% (92% to 100%) | 2.7 (2 to 3) of 3 |
| phonenumbers | phone_number_parsing_and_formatting | 3 | 18% (7% to 32%) | 18% (7% to 32%) | 1.0 of 3 |
| pyluach | jewish_holidays_and_fasts | 3 | 39% (0% to 62%) | 39% (0% to 62%) | 1.0 (0 to 2) of 4 |
| python-stdnum | iban_validation | 3 | 45% (0% to 93%) | 50% (0% to 95%) | 1.3 (0 to 3) of 3 |

## Tools left without a valid case

- hijridate run 1: convert_gregorian_to_hijri, get_hijri_date_properties. First problem: `NameError("name 'Hijridate' is not defined") running: Hijridate.convert.Hijri.fromisoformat('1445-01-01').month_name()`
- hijridate run 2: convert_gregorian_to_hijri. First problem: `OverflowError("year must be in 1343-1500, got '2000'") running: Hijri.fromisoformat("2000-01-01").isoformat()`
- hijridate run 3: convert_gregorian_to_hijri. First problem: `no case`
- networkx run 1: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `AttributeError("'NoneType' object has no attribute 'dijkstra_path_length'") running: networkx.Graph().add_weighted_edges_from([["A", "B", 5], ["B", "C", 10], ["A", "C", 20]]).dijkstra_path_length("A", "C", weight="weight")`
- networkx run 2: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `AttributeError("'NoneType' object has no attribute 'dijkstra_path_length'") running: networkx.Graph().add_weighted_edges_from([["A", "B", 5], ["B", "C", 10], ["A", "C", 20]]).dijkstra_path_length("A", "C", weight="weight")`
- networkx run 3: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `syntax error: closing parenthesis ']' does not match opening parenthesis '('`
- packaging run 3: check_version_matches_specifier. First problem: `no case`
- phonenumbers run 1: format_phone_number, get_carrier_info. First problem: `no case`
- phonenumbers run 2: format_phone_number, get_carrier_info. First problem: `NameError("name 'format_number' is not defined") running: format_number(numobj, 'INTERNATIONAL')`
- phonenumbers run 3: get_carrier_info, parse_and_analyze_phone_number. First problem: `AttributeError("module 'phonenumbers' has no attribute 'phonenumbers'") running: phonenumbers.phonenumberutil.parse(phonenumbers.phonenumberutil.PhoneNumber(), phonenumbers.phonenumbers.phonenumberutil.parse(phonenumbers.phonenumbers.phonen`
- pyluach run 1: get_festival_info, get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `no case`
- pyluach run 2: get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `no case`
- pyluach run 3: get_festival_info, get_hebrew_date_from_gregorian, get_holiday_info, get_today_jewish_date. First problem: `NameError("name 'date_str' is not defined") running: pyluach.hebrewcal.holiday(pyluach.dates.GregorianDate({date_str[0:4]}, {date_str[5:7]}, {date_str[8:10]}), israel='{is_israel}', hebrew='{hebrew_names}', prefix_day='{hebrew_prefix_day}')`
- python-stdnum run 1: calculate_iban_check_digits, format_iban, validate_iban. First problem: `syntax error: invalid syntax`
- python-stdnum run 3: calculate_iban_check_digits, format_iban. First problem: `no case`
