// Farm boundary geometry, kept identical to the server
// (dashboard/services/farmer_service.py: clean_polygon, polygon_area_centroid)
// so the app can tell the farmer before sending that a shape will be refused.
import 'dart:math' as math;

import 'package:latlong2/latlong.dart';

const double earthRadiusM = 6371008.8;

/// Same limits as the server (MIN_AREA_HA, MAX_AREA_HA, MAX_VERTICES).
const double minAreaHa = 0.01;
const double maxAreaHa = 10000;
const int maxCorners = 999; // the closed ring repeats the first corner: 1000 points

/// Area in hectares of the shape through [corners] (open ring, any direction).
/// Local equirectangular projection around the mean latitude, like the server.
double areaHa(List<LatLng> corners) {
  if (corners.length < 3) return 0;
  final ring = [...corners, corners.first];
  final lat0 = ring.map((p) => p.latitude).reduce((a, b) => a + b) / ring.length * math.pi / 180;
  double x(LatLng p) => p.longitude * math.pi / 180 * earthRadiusM * math.cos(lat0);
  double y(LatLng p) => p.latitude * math.pi / 180 * earthRadiusM;
  var a = 0.0;
  for (var i = 0; i < ring.length - 1; i++) {
    a += x(ring[i]) * y(ring[i + 1]) - x(ring[i + 1]) * y(ring[i]);
  }
  return (a / 2).abs() / 10000;
}

/// Why the server would refuse this shape (an i18n key), or null when it is fine.
String? boundaryProblem(List<LatLng> corners) {
  if (corners.length < 3) return 'needThreeCorners';
  if (corners.length > maxCorners) return 'tooManyCorners';
  final ha = areaHa(corners);
  if (ha < minAreaHa) return 'parcelTooSmall';
  if (ha > maxAreaHa) return 'parcelTooLarge';
  return null;
}

/// GeoJSON Polygon with one closed ring of [lon, lat], as the server stores it.
Map<String, dynamic> toGeoJson(List<LatLng> corners) => {
      'type': 'Polygon',
      'coordinates': [
        [
          for (final p in [...corners, corners.first]) [_round(p.longitude), _round(p.latitude)],
        ],
      ],
    };

double _round(double v) => (v * 1e7).roundToDouble() / 1e7;

/// The corners of a stored boundary (the closing point dropped); empty if unreadable.
List<LatLng> fromGeoJson(Object? boundary) {
  try {
    final ring = ((boundary as Map)['coordinates'] as List).first as List;
    final pts = [
      for (final p in ring) LatLng(((p as List)[1] as num).toDouble(), (p[0] as num).toDouble()),
    ];
    if (pts.length > 1 && pts.first == pts.last) pts.removeLast();
    return pts;
  } catch (_) {
    return const [];
  }
}
