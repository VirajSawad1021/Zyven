# Tester validity: after-e4b (2026-11-26)

- **Model:** `gemma4:e4b@possibilities-monte-bargains-highly.trycloudflare.com`
- **Code:** commit `6adfa80`
- **Valid** means the reference program evaluates in the sandbox on its own case's arguments; whether it
  matches a tool is not measured. Specs are frozen (`eval/tester_specs/`), so only the Tester varies.
- hijridate run 1 timed out at the model host and was rerun once on the same commit.
- Each cell is the mean over runs, with the range when runs differ.

| Library | Capability | Runs | (a) valid, Tester's answer | (b) valid, after re-ask | (c) tools with a valid case |
|---|---|---|---|---|---|
| hijridate | hijri_gregorian_conversion | 3 | 35% (8% to 69%) | 54% (18% to 75%) | 1.7 (1 to 2) of 3 |
| networkx | graph_algorithms | 3 | 0% | 19% (0% to 52%) | 1.0 (0 to 2) of 6 |
| packaging | version_specifiers | 3 | 93% (90% to 94%) | 94% (91% to 96%) | 3.0 of 3 |
| phonenumbers | phone_number_parsing_and_formatting | 3 | 4% (0% to 6%) | 7% (6% to 10%) | 1.0 of 3 |
| pyluach | jewish_holidays_and_fasts | 3 | 33% (0% to 75%) | 49% (23% to 92%) | 1.3 (1 to 2) of 4 |
| python-stdnum | iban_validation | 3 | 63% (42% to 88%) | 72% (60% to 88%) | 3.0 of 3 |

## Tools left without a valid case

- hijridate run 1: convert_gregorian_to_hijri. First problem: `no case`
- hijridate run 2: convert_gregorian_to_hijri, get_hijri_date_properties. First problem: `NameError("name 'Hijri' is not defined") running: Hijri.fromisoformat('1999-12-31').to_hijri().isoformat()`
- hijridate run 3: convert_gregorian_to_hijri. First problem: `no case`
- networkx run 1: count_connected_components, count_triangles, highest_betweenness_centrality_node, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `NameError("name 'dijkstra_path_length' is not defined") running: G = networkx.Graph()
G.add_weighted_edges_from([['A', 'B', 5], ['B', 'C', 10], ['A', 'C', 20]])
dijkstra_path_length(G, 'A', 'C', weight='weight')`
- networkx run 2: count_connected_components, count_triangles, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `syntax error: unterminated string literal (detected at line 1) (line 1) in: nx.Graph().add_weighted_edges_from([["{edges[0][0]}", "{edges[0][1]}", {edges[0][2]}"], [["{edges[1][0]}", "{edges[1][1]}", {edges[1][2]}"], [["{edges[2][0]}", "{ed`
- networkx run 3: count_triangles, max_flow_value, mst_total_weight, shortest_path_weight. First problem: `NameError("name 'nx' is not defined") running: nx.Graph().add_weighted_edges_from([("[['A', 'B', 5], ['B', 'C', 10], ['A', 'C', 20]][0][0]", "[['A', 'B', 5], ['B', 'C', 10], ['A', 'C', 20]][0][1]", [['A', 'B', 5], ['B', 'C', 10], ['A', 'C',`
- phonenumbers run 1: get_carrier_info, parse_and_analyze_phone_number. First problem: `AttributeError("'PhoneNumber' object has no attribute 'is_valid_number'") running: phonenumbers.parse('+1 415 555 2671', 'US').is_valid_number()`
- phonenumbers run 2: get_carrier_info, parse_and_analyze_phone_number. First problem: `AttributeError("'PhoneNumber' object has no attribute 'is_valid_number'") running: phonenumbers.parse('+1 415 555 2671', 'US').is_valid_number()`
- phonenumbers run 3: format_phone_number, get_carrier_info. First problem: `AttributeError("'PhoneNumber' object has no attribute 'format_number'") running: phonenumbers.parse('+14155552671', None).format_number(phonenumbers.PhoneNumberFormat.INTERNATIONAL)`
- pyluach run 1: get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `no case`
- pyluach run 2: get_festival_info, get_holiday_info, get_today_jewish_date. First problem: `TypeError("'NoneType' object is not subscriptable") running: pyluach.hebrewcal.holiday(pyluach.dates.GregorianDate(2023, 4, 5), israel=False, hebrew=False, prefix_day=False)[2]`
- pyluach run 3: get_festival_info, get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `AttributeError("'NoneType' object has no attribute 'festival_is_festival'") running: pyluach.hebrewcal.festival(pyluach.dates.GregorianDate(2023, 4, 5), israel=False, hebrew=False, include_working_days=False).festival_is_festival`
