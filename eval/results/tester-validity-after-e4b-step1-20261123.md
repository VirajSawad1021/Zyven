# Tester validity: after-e4b (2026-11-23)

- **Model:** `gemma4:e4b@kaggle-t4-ollama`
- **Code:** commit `40177ae`
- **Valid** means the reference program evaluates in the sandbox on its own case's arguments; whether it
  matches a tool is not measured. Specs are frozen (`eval/tester_specs/`), so only the Tester varies.
- Each cell is the mean over runs, with the range when runs differ.

| Library | Capability | Runs | (a) valid, Tester's answer | (b) valid, after re-ask | (c) tools with a valid case |
|---|---|---|---|---|---|
| hijridate | hijri_gregorian_conversion | 3 | 42% (27% to 50%) | 48% (39% to 53%) | 2.0 of 3 |
| networkx | graph_algorithms | 3 | 0% | 0% | 0.0 of 6 |
| packaging | version_specifiers | 3 | 96% (88% to 100%) | 97% (91% to 100%) | 2.7 (2 to 3) of 3 |
| phonenumbers | phone_number_parsing_and_formatting | 3 | 22% (10% to 40%) | 22% (10% to 40%) | 1.0 of 3 |
| pyluach | jewish_holidays_and_fasts | 3 | 27% (0% to 80%) | 36% (0% to 90%) | 0.7 (0 to 1) of 4 |
| python-stdnum | iban_validation | 3 | 87% (86% to 89%) | 91% (87% to 93%) | 3.0 of 3 |

## Tools left without a valid case

- hijridate run 1: convert_gregorian_to_hijri. First problem: `no case`
- hijridate run 2: convert_gregorian_to_hijri. First problem: `no case`
- hijridate run 3: convert_gregorian_to_hijri. First problem: `no case`
- networkx run 1: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `AttributeError("'NoneType' object has no attribute 'dijkstra_path_length'") running: networkx.classes.graph.Graph().add_weighted_edges_from([["A", "B", 5], ["B", "C", 10], ["A", "C", 20]]).dijkstra_path_length("A", "C", weight='weight')`
- networkx run 2: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `AttributeError("'NoneType' object has no attribute 'dijkstra_path_length'") running: networkx.Graph().add_weighted_edges_from([["A", "B", 5], ["B", "C", 10], ["A", "C", 20]]).dijkstra_path_length("A", "C", weight="weight")`
- networkx run 3: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `AttributeError("'NoneType' object has no attribute 'dijkstra_path_length'") running: networkx.Graph().add_weighted_edges_from([["A", "B", 5], ["B", "C", 10], ["A", "C", 20]]).dijkstra_path_length("A", "C", weight="weight")`
- packaging run 1: check_version_matches_specifier. First problem: `no case`
- phonenumbers run 1: format_phone_number, get_carrier_info. First problem: `no case`
- phonenumbers run 2: get_carrier_info, parse_and_analyze_phone_number. First problem: `AttributeError("'PhoneNumber' object has no attribute 'is_valid_number'") running: phonenumbers.parse('+1 415 555 2671', 'US').is_valid_number()`
- phonenumbers run 3: get_carrier_info, parse_and_analyze_phone_number. First problem: `AttributeError("'PhoneNumber' object has no attribute 'is_valid_number'") running: phonenumbers.parse('+1 415 555 2671', 'US').is_valid_number()`
- pyluach run 1: get_festival_info, get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `AttributeError("'function' object has no attribute 'festival'") running: pyluach.hebrewcal.festival.festival(greg_date, israel=False, hebrew=False, include_working_days=False, prefix_day=False).festival_name`
- pyluach run 2: get_festival_info, get_hebrew_date_from_gregorian, get_holiday_info, get_today_jewish_date. First problem: `AttributeError("module 'pyluach' has no attribute 'hebrewcal'") running: pyluach.hebrewcal.holiday(pyluach.dates.GregorianDate(2023, 4, 5), israel=False, hebrew=False, prefix_day=False)`
- pyluach run 3: get_festival_info, get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `NameError("name 'date_str' is not defined") running: pyluach.dates.GregorianDate(int({date_str[:4]}), int({date_str[5:7]}), int({date_str[8:10]})).festival(False, name_is_hebrew, include_working_days)`
