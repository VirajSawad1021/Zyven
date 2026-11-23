# Tester validity: before-e4b (2026-11-23)

- **Model:** `gemma4:e4b@kaggle-t4-ollama`
- **Code:** commit `2ed91e4` (measurement only, Tester unchanged)
- **Valid** means the reference program evaluates in the sandbox on its own case's arguments; whether it
  matches a tool is not measured. Specs are frozen (`eval/tester_specs/`), so only the Tester varies.
- Each cell is the mean over runs, with the range when runs differ.

| Library | Capability | Runs | (a) valid, Tester's answer | (b) valid, after re-ask | (c) tools with a valid case |
|---|---|---|---|---|---|
| hijridate | hijri_gregorian_conversion | 3 | 6% (0% to 11%) | 5% (0% to 11%) | 0.7 (0 to 1) of 3 |
| networkx | graph_algorithms | 3 | 0% | 0% | 0.0 of 6 |
| packaging | version_specifiers | 3 | 99% (96% to 100%) | 99% (96% to 100%) | 3.0 of 3 |
| phonenumbers | phone_number_parsing_and_formatting | 3 | 8% (0% to 25%) | 11% (0% to 32%) | 0.3 (0 to 1) of 3 |
| pyluach | jewish_holidays_and_fasts | 3 | 18% (0% to 38%) | 23% (18% to 29%) | 1.0 of 4 |
| python-stdnum | iban_validation | 3 | 71% (67% to 75%) | 71% (67% to 75%) | 2.3 (1 to 3) of 3 |

## Tools left without a valid case

- hijridate run 1: convert_gregorian_to_hijri, convert_hijri_to_gregorian, get_hijri_date_properties. First problem: `NameError("name 'Hijri' is not defined") running: Hijri.fromisoformat('1410-08-13').to_gregorian().isoformat()`
- hijridate run 2: convert_hijri_to_gregorian, get_hijri_date_properties. First problem: `NameError("name 'Hijri' is not defined") running: Hijri.fromisoformat('1410-08-13').to_gregorian().isoformat()`
- hijridate run 3: convert_gregorian_to_hijri, get_hijri_date_properties. First problem: `NameError("name 'Hijri' is not defined") running: Hijri.fromisoformat('1990-03-10').isoformat()`
- networkx run 1: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `syntax error: closing parenthesis ']' does not match opening parenthesis '('`
- networkx run 2: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `AttributeError("'NoneType' object has no attribute 'dijkstra_path_length'") running: nx.Graph().add_weighted_edges_from([["A", "B", 5], ["B", "C", 10]]).dijkstra_path_length("A", "C", weight="weight")`
- networkx run 3: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `NameError("name 'nx' is not defined") running: nx.Graph().add_weighted_edges_from([["A", "B", 5], ["B", "C", 10], ["A", "C", 20]]).dijkstra_path_length("A", "C", weight='weight')`
- phonenumbers run 1: format_phone_number, get_carrier_info, parse_and_analyze_phone_number. First problem: `AttributeError("'PhoneNumber' object has no attribute 'is_valid_number'") running: phonenumbers.parse(str('+1 415 555 2671'), str('US')).is_valid_number()`
- phonenumbers run 2: get_carrier_info, parse_and_analyze_phone_number. First problem: `TypeError("object of type 'PhoneNumber' has no len()") running: str(phonenumbers.phonenumberutil.parse(phonenumbers.PhoneNumber(), '+1 415 555 2671', 'US').is_valid_number) + ', Type: ' + phonenumbers.phonenumberutil.number_type(phonenumber`
- phonenumbers run 3: format_phone_number, get_carrier_info, parse_and_analyze_phone_number. First problem: `AttributeError("'PhoneNumber' object has no attribute 'is_valid_number'") running: phonenumbers.parse('+1 415 555 2671', 'US').is_valid_number()`
- pyluach run 1: get_festival_info, get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `AttributeError("'function' object has no attribute 'festival'") running: pyluach.hebrewcal.festival.festival(pyluach.dates.GregorianDate(2023, 4, 5), israel=False, hebrew=False, include_working_days=False)`
- pyluach run 2: get_festival_info, get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `TypeError("GregorianDate.__init__() missing 2 required positional arguments: 'month' and 'day'") running: pyluach.dates.GregorianDate('2024-04-01').festival(israel=False, hebrew=False, include_working_days=False)`
- pyluach run 3: get_festival_info, get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `TypeError("GregorianDate.__init__() missing 2 required positional arguments: 'month' and 'day'") running: pyluach.dates.GregorianDate('2024-04-14').festival(israel=False, hebrew=False, include_working_days=False, prefix_day=False)`
- python-stdnum run 2: calculate_iban_check_digits, format_iban. First problem: `no case`
