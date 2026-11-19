import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../basin.dart';
import '../format.dart';
import '../geo.dart';
import '../i18n.dart';

/// A position from the phone, with its accuracy in metres.
typedef Fix = ({LatLng point, double accuracy});

/// Thrown by a [Locator] with the i18n key of what went wrong.
class GpsException implements Exception {
  GpsException(this.key);
  final String key;
}

typedef Locator = Future<Fix> Function();

/// The phone's GPS position, asking for permission when needed.
Future<Fix> phonePosition() async {
  if (!await Geolocator.isLocationServiceEnabled()) throw GpsException('gpsOff');
  var perm = await Geolocator.checkPermission();
  if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
  if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
    throw GpsException('gpsDenied');
  }
  try {
    final p = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(accuracy: LocationAccuracy.best, timeLimit: Duration(seconds: 30)),
    );
    return (point: LatLng(p.latitude, p.longitude), accuracy: p.accuracy);
  } catch (_) {
    throw GpsException('gpsFailed');
  }
}

/// Mark a farm's corners on the map: tapped on the satellite view, or walked
/// with the GPS. Creates the farm (with [farm] null) or replaces its border.
/// Pops the farm as the server returns it, or null when nothing was saved.
class BoundaryScreen extends StatefulWidget {
  const BoundaryScreen({super.key, this.farm, this.locate = phonePosition, this.showTiles = true});
  final Map<String, dynamic>? farm;
  final Locator locate;

  /// Off in tests: the map images come from the network.
  final bool showTiles;

  @override
  State<BoundaryScreen> createState() => _BoundaryScreenState();
}

class _BoundaryScreenState extends State<BoundaryScreen> {
  final _map = MapController();
  final _name = TextEditingController();
  late List<LatLng> _corners;
  LatLng? _me;
  bool _satellite = true;
  bool _locating = false;
  bool _busy = false;
  String? _error;

  /// The Ichkeul catchment borders, drawn under the farm as on the website.
  Basin? _basin;

  bool get _isNew => widget.farm == null;

  @override
  void initState() {
    super.initState();
    _corners = [...fromGeoJson(widget.farm?['boundary'])];
    if (widget.showTiles) {
      loadBasin().then((b) {
        if (mounted) setState(() => _basin = b);
      });
    }
    // A new farm: start where the farmer stands, usually on the land itself.
    if (_isNew) WidgetsBinding.instance.addPostFrameCallback((_) => _locate(addCorner: false, quiet: true));
  }

  @override
  void dispose() {
    _name.dispose();
    _map.dispose();
    super.dispose();
  }

  Future<void> _locate({required bool addCorner, bool quiet = false}) async {
    if (_locating) return;
    setState(() => _locating = true);
    try {
      final fix = await widget.locate();
      if (!mounted) return;
      setState(() {
        _me = fix.point;
        if (addCorner) _corners.add(fix.point);
        _error = null;
      });
      try {
        _map.move(fix.point, addCorner ? _map.camera.zoom.clamp(17, 20).toDouble() : 17);
      } catch (_) {}
      if (addCorner) {
        final m = fmtNum(fix.accuracy);
        showMessage(context, t(fix.accuracy > 15 ? 'gpsWeak' : 'cornerAdded', {'m': m}), error: fix.accuracy > 15);
      }
    } on GpsException catch (e) {
      if (mounted && !quiet) showMessage(context, t(e.key), error: true);
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  /// A tap on an existing corner removes it; anywhere else adds one.
  void _tap(LatLng p) {
    final cam = _map.camera;
    final tapped = cam.latLngToScreenOffset(p);
    for (var i = 0; i < _corners.length; i++) {
      if ((cam.latLngToScreenOffset(_corners[i]) - tapped).distance < 22) {
        setState(() => _corners.removeAt(i));
        return;
      }
    }
    setState(() => _corners.add(p));
  }

  Future<void> _save() async {
    final problem = boundaryProblem(_corners);
    final name = _name.text.trim();
    if (problem != null || (_isNew && name.isEmpty)) {
      setState(() => _error = t(problem ?? 'nameRequired'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final boundary = toGeoJson(_corners);
      final data = _isNew
          ? await Api.I.post('/farmer/api/farms/', {'name': name, 'boundary': boundary})
          : await Api.I.patch('/farmer/api/farms/${widget.farm!['id']}/', {'boundary': boundary});
      if (!mounted) return;
      showMessage(context, t(_isNew ? 'farmCreated' : 'borderSaved'));
      Navigator.pop(context, Map<String, dynamic>.from(data['farm'] as Map));
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  MapOptions get _options {
    final start = _corners.length >= 2
        ? CameraFit.bounds(bounds: LatLngBounds.fromPoints(_corners), padding: const EdgeInsets.all(48), maxZoom: 18)
        : null;
    return MapOptions(
      initialCenter: _corners.isNotEmpty ? _corners.first : Basin.centre,
      initialZoom: _corners.isNotEmpty ? 17 : Basin.zoom,
      initialCameraFit: start,
      maxZoom: 20,
      backgroundColor: const Color(0xFFE8EDE6),
      interactionOptions: const InteractionOptions(flags: InteractiveFlag.all & ~InteractiveFlag.rotate),
      onTap: (_, p) => _tap(p),
    );
  }

  Widget _mapView() {
    return FlutterMap(
      mapController: _map,
      options: _options,
      children: [
        if (widget.showTiles)
          TileLayer(
            // Same server tile proxy as the website (cached Esri basemaps).
            urlTemplate: '${Api.I.base}/api/tiles/{z}/{x}/{y}.png?layer=${_satellite ? 'satellite' : 'map'}',
            userAgentPackageName: 'tn.apwrs.apwrs_farmer',
            maxNativeZoom: 19,
            maxZoom: 20,
          ),
        if (_basin != null) ..._basinLayers(_basin!),
        if (_corners.length >= 3)
          PolygonLayer(polygons: [
            Polygon(
              points: _corners,
              color: const Color(0x55FACC15),
              borderColor: const Color(0xFFFACC15),
              borderStrokeWidth: 3,
            ),
          ])
        else if (_corners.length == 2)
          PolylineLayer(polylines: [Polyline(points: _corners, color: const Color(0xFFFACC15), strokeWidth: 3)]),
        MarkerLayer(markers: [
          if (_me != null)
            Marker(
              point: _me!,
              width: 22,
              height: 22,
              child: Container(
                decoration: BoxDecoration(
                  color: kWater,
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white, width: 3),
                ),
              ),
            ),
          for (var i = 0; i < _corners.length; i++)
            Marker(
              point: _corners[i],
              width: 30,
              height: 30,
              child: Container(
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: const Color(0xFFFACC15),
                  shape: BoxShape.circle,
                  border: Border.all(color: kPrimary, width: 2),
                ),
                child: Text('${i + 1}',
                    style: const TextStyle(color: kPrimary, fontWeight: FontWeight.w800, fontSize: 12)),
              ),
            ),
        ]),
        if (widget.showTiles) const SimpleAttributionWidget(source: Text('Esri, Maxar, Earthstar Geographics')),
      ],
    );
  }

  /// The website's basin style: thin section lines, and the catchment edge as
  /// a light line on a dark halo (on the street map, dark lines instead).
  List<Widget> _basinLayers(Basin b) {
    final light = _satellite;
    return [
      PolylineLayer(polylines: [
        for (final s in b.sections)
          Polyline(
            points: s,
            strokeWidth: 0.8,
            color: light ? const Color(0x99FFFFFF) : const Color(0x80414844),
          ),
      ]),
      PolylineLayer(polylines: [
        Polyline(points: b.outline, strokeWidth: 5, color: light ? const Color(0xBF0B1A22) : const Color(0x40FFFFFF)),
        Polyline(points: b.outline, strokeWidth: 2, color: light ? Colors.white : kPrimary),
      ]),
    ];
  }

  Widget _panel() {
    final problem = boundaryProblem(_corners);
    final ha = areaHa(_corners);
    return Material(
      elevation: 8,
      color: kSurface,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(t('drawHint'), style: const TextStyle(fontSize: 13, color: kText)),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                child: Text(
                  t('cornersArea', {'n': _corners.length, 'ha': fmtNum(ha, ha < 10 ? 2 : 1)}),
                  key: const ValueKey('corners-area'),
                  style: hl(15, weight: FontWeight.w700),
                ),
              ),
              IconButton(
                tooltip: t('undo'),
                icon: const Icon(Icons.undo),
                onPressed: _corners.isEmpty ? null : () => setState(() => _corners.removeLast()),
              ),
              IconButton(
                tooltip: t('clear'),
                icon: const Icon(Icons.delete_sweep_outlined),
                onPressed: _corners.isEmpty ? null : () => setState(() => _corners.clear()),
              ),
            ]),
            OutlinedButton.icon(
              icon: _locating
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.add_location_alt_outlined),
              label: Text(t('cornerHere')),
              onPressed: _locating ? null : () => _locate(addCorner: true),
            ),
            if (_isNew) ...[
              const SizedBox(height: 10),
              TextField(
                key: const ValueKey('farm-name'),
                controller: _name,
                maxLength: 100,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(labelText: t('farmName'), isDense: true, counterText: ''),
              ),
            ],
            if (_error != null || (problem != null && _corners.isNotEmpty))
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(_error ?? t(problem!),
                    style: TextStyle(color: _error != null ? kDanger : kWarn, fontWeight: FontWeight.w600)),
              ),
            const SizedBox(height: 10),
            FilledButton.icon(
              icon: _busy
                  ? const SizedBox(
                      width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.check),
              label: Text(t('save')),
              onPressed: _busy || problem != null ? null : _save,
            ),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_isNew ? t('drawFarm') : t('redrawBorder')),
        actions: [
          if (widget.showTiles)
            IconButton(
              tooltip: t('switchLayer'),
              icon: Icon(_satellite ? Icons.map_outlined : Icons.satellite_alt_outlined),
              onPressed: () => setState(() => _satellite = !_satellite),
            ),
        ],
      ),
      body: Column(children: [
        offlineBanner(),
        Expanded(
          child: Stack(children: [
            Positioned.fill(child: _mapView()),
            PositionedDirectional(
              end: 12,
              top: 12,
              child: FloatingActionButton.small(
                heroTag: 'me',
                tooltip: t('myLocation'),
                backgroundColor: Colors.white,
                foregroundColor: kPrimary,
                onPressed: _locating ? null : () => _locate(addCorner: false),
                child: const Icon(Icons.my_location),
              ),
            ),
          ]),
        ),
        _panel(),
      ]),
    );
  }
}
