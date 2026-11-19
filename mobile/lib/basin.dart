// The Ichkeul catchment drawn on the website's maps: its outline and the 29
// grid sections (static/dashboard/data/ichkeul_basin.geojson, bundled so the
// borders show without a connection).
import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;
import 'package:latlong2/latlong.dart';

class Basin {
  const Basin({required this.outline, required this.sections});
  final List<LatLng> outline;
  final List<List<LatLng>> sections;

  /// Centre and zoom that show the whole basin on a phone.
  static final centre = LatLng(37.0635, 9.4834);
  static const zoom = 9.6;
}

Future<Basin>? _basin;

/// The basin, read once.
Future<Basin> loadBasin() => _basin ??= _read();

Future<Basin> _read() async {
  final data = jsonDecode(await rootBundle.loadString('assets/data/ichkeul_basin.geojson')) as Map;
  List<LatLng> ring(Map feature) => [
        for (final p in ((feature['geometry'] as Map)['coordinates'] as List).first as List)
          LatLng(((p as List)[1] as num).toDouble(), (p[0] as num).toDouble()),
      ];
  var outline = <LatLng>[];
  final sections = <List<LatLng>>[];
  for (final f in (data['features'] as List).cast<Map>()) {
    final kind = (f['properties'] as Map?)?['kind'];
    if (kind == 'outline') {
      outline = ring(f);
    } else if (kind == 'section') {
      sections.add(ring(f));
    }
  }
  return Basin(outline: outline, sections: sections);
}
