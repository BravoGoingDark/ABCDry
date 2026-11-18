import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';
import 'boundary_screen.dart';
import 'crop_tab.dart' show cropName, monthName;

const irrigationMethods = ['drip', 'sprinkler', 'surface'];

/// Edit the farm: name, crop, sowing date, irrigation and its border on the
/// map. Pops true when anything was saved or the farm was deleted.
class FarmSettingsScreen extends StatefulWidget {
  const FarmSettingsScreen({super.key, required this.farm, this.initialCrop});
  final Map<String, dynamic> farm;

  /// Crop picked from "what grows best here", pre-selected in the form.
  final String? initialCrop;

  @override
  State<FarmSettingsScreen> createState() => _FarmSettingsScreenState();
}

class _FarmSettingsScreenState extends State<FarmSettingsScreen> {
  late final TextEditingController _name;
  late final TextEditingController _flow;
  late final TextEditingController _supply;
  late Future<dynamic> _crops;
  String? _crop;
  String? _sowing;
  late bool _irrigated;
  String? _method;
  String? _error;
  bool _busy = false;

  /// The border is saved on its own (from the map): the home tabs must reload
  /// even if the form is then left without saving.
  bool _borderChanged = false;
  late num? _area = f['area_ha'] as num?;
  late Object? _boundary = f['boundary'];

  Map<String, dynamic> get f => widget.farm;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: '${f['name'] ?? ''}');
    _flow = TextEditingController(text: f['irrigation_flow_m3h'] != null ? fmtPlain(f['irrigation_flow_m3h']) : '');
    _supply = TextEditingController(text: f['water_supply_mm'] != null ? fmtPlain(f['water_supply_mm']) : '');
    _crop = widget.initialCrop ?? f['crop'] as String?;
    // A different crop starts with no sowing date: the old one belonged to the old crop.
    _sowing = _crop == f['crop'] ? f['sowing_date'] as String? : null;
    _irrigated = f['irrigated'] == true;
    _method = f['irrigation_method'] as String?;
    _crops = Api.I.get('/farmer/api/crops/');
  }

  @override
  void dispose() {
    _name.dispose();
    _flow.dispose();
    _supply.dispose();
    super.dispose();
  }

  /// Number typed with a comma or a point; null when empty; NaN when invalid.
  static double? _number(String text) {
    final s = text.replaceAll(',', '.').replaceAll(' ', '').trim();
    if (s.isEmpty) return null;
    return double.tryParse(s) ?? double.nan;
  }

  /// The PATCH body, or null with [_error] set.
  Map<String, dynamic>? _body() {
    final name = _name.text.trim();
    if (name.isEmpty) {
      _error = t('nameRequired');
      return null;
    }
    final body = <String, dynamic>{
      'name': name,
      'crop': _crop ?? '',
      'sowing_date': _sowing,
      'irrigated': _irrigated,
    };
    if (_irrigated) {
      final flow = _number(_flow.text);
      final supply = _number(_supply.text);
      if ((flow != null && (flow.isNaN || flow <= 0)) || (supply != null && (supply.isNaN || supply < 0))) {
        _error = t('badNumber');
        return null;
      }
      body['irrigation_method'] = _method ?? '';
      body['irrigation_flow_m3h'] = flow;
      body['water_supply_mm'] = supply;
    } else {
      body['water_supply_mm'] = null;
    }
    _error = null;
    return body;
  }

  Future<void> _save() async {
    final body = _body();
    if (body == null) {
      setState(() {});
      return;
    }
    setState(() => _busy = true);
    try {
      await Api.I.patch('/farmer/api/farms/${f['id']}/', body);
      if (!mounted) return;
      showMessage(context, t('saved'));
      Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _redraw() async {
    final saved = await Navigator.push<Map<String, dynamic>>(
        context, MaterialPageRoute(builder: (_) => BoundaryScreen(farm: {...f, 'boundary': _boundary})));
    if (saved == null || !mounted) return;
    setState(() {
      _boundary = saved['boundary'];
      _borderChanged = true;
      _area = saved['area_ha'] as num?;
    });
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(t('deleteFarm')),
        content: Text(t('deleteFarmConfirm', {'name': f['name']})),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t('cancel'))),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: kDanger),
            onPressed: () => Navigator.pop(c, true),
            child: Text(t('delete')),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await Api.I.delete('/farmer/api/farms/${f['id']}/');
      if (!mounted) return;
      showMessage(context, t('farmDeleted'));
      Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pickSowing(bool perennial) async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _sowing != null ? parseDay(_sowing!) : now,
      firstDate: DateTime(now.year - (perennial ? 60 : 2)),
      lastDate: DateTime(now.year + 1, 12, 31),
    );
    if (picked != null) setState(() => _sowing = isoDay(picked));
  }

  Widget _label(String text) => Padding(
        padding: const EdgeInsets.only(top: 18, bottom: 6),
        child: Text(text, style: const TextStyle(fontWeight: FontWeight.w600, color: kPrimary)),
      );

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_borderChanged,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) Navigator.pop(context, true);
      },
      child: Scaffold(
        appBar: AppBar(title: Text(t('farmSettings'))),
        body: Column(children: [
          offlineBanner(),
          Expanded(
            child: FutureBuilder<dynamic>(
              future: _crops,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snap.hasError) {
                  return errorView(
                      snap.error!,
                      () => setState(() {
                            _crops = Api.I.get('/farmer/api/crops/');
                          }));
                }
                final crops = ((snap.data['crops'] as List?) ?? const []).cast<Map>().toList()
                  ..sort((a, b) => cropName(a['names']).compareTo(cropName(b['names'])));
                final current = crops.where((c) => c['key'] == _crop).firstOrNull;
                final perennial = current?['perennial'] == true;
                final months = ((current?['planting_months'] as List?) ?? const []).cast<int>();
                return ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
                  _label(t('farmName')),
                  TextField(controller: _name, maxLength: 100, textCapitalization: TextCapitalization.sentences),
                  _label(t('cropLabel')),
                  DropdownButtonFormField<String>(
                    key: const ValueKey('crop-field'),
                    initialValue: current != null ? _crop : '',
                    isExpanded: true,
                    items: [
                      DropdownMenuItem(value: '', child: Text(t('noCrop'))),
                      for (final c in crops)
                        DropdownMenuItem(value: c['key'] as String, child: Text(cropName(c['names'], '${c['key']}'))),
                    ],
                    onChanged: (v) => setState(() {
                      final changed = (v == '' ? null : v) != _crop;
                      _crop = v == '' ? null : v;
                      if (changed) _sowing = null;
                    }),
                  ),
                  if (_crop != null && months.isNotEmpty && !perennial)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text(t('sowingMonths', {'m': months.map(monthName).join(', ')}),
                          style: const TextStyle(fontSize: 12.5, color: kSubtle)),
                    ),
                  if (_crop != null) ...[
                    _label(t(perennial ? 'plantedOn' : 'sowingDate')),
                    Row(children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          icon: const Icon(Icons.event),
                          label: Text(_sowing != null ? fmtDate(_sowing!) : t('notSownYet')),
                          onPressed: () => _pickSowing(perennial),
                        ),
                      ),
                      if (_sowing != null)
                        IconButton(
                          tooltip: t('clear'),
                          icon: const Icon(Icons.clear),
                          onPressed: () => setState(() => _sowing = null),
                        ),
                    ]),
                  ],
                  _label(t('waterSource')),
                  SegmentedButton<bool>(
                    segments: [
                      ButtonSegment(value: false, label: Text(t('rainfed')), icon: const Icon(Icons.cloud)),
                      ButtonSegment(value: true, label: Text(t('irrigated')), icon: const Icon(Icons.water_drop)),
                    ],
                    selected: {_irrigated},
                    onSelectionChanged: (v) => setState(() => _irrigated = v.first),
                  ),
                  if (_irrigated) ...[
                    _label(t('irrigationMethod')),
                    Wrap(spacing: 8, runSpacing: 8, children: [
                      for (final m in irrigationMethods)
                        ChoiceChip(
                          label: Text(t('m_$m')),
                          selected: _method == m,
                          onSelected: (on) => setState(() => _method = on ? m : null),
                        ),
                    ]),
                    _label(t('flowRate')),
                    TextField(
                      key: const ValueKey('flow-field'),
                      controller: _flow,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(suffixText: t('m3h'), helperText: t('flowHint'), helperMaxLines: 3),
                    ),
                    _label(t('waterSupply')),
                    TextField(
                      key: const ValueKey('supply-field'),
                      controller: _supply,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(suffixText: t('mm'), helperText: t('supplyHint'), helperMaxLines: 3),
                    ),
                  ],
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 16),
                      child: Text(_error!, style: const TextStyle(color: kDanger, fontWeight: FontWeight.w600)),
                    ),
                  const SizedBox(height: 22),
                  FilledButton.icon(
                    icon: _busy
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : const Icon(Icons.check),
                    label: Text(t('save')),
                    onPressed: _busy ? null : _save,
                  ),
                  _label(_area != null ? t('farmArea', {'ha': fmtNum(_area, 2)}) : t('redrawBorder')),
                  OutlinedButton.icon(
                    icon: const Icon(Icons.edit_location_alt_outlined),
                    label: Text(t('redrawBorder')),
                    onPressed: _busy ? null : _redraw,
                  ),
                  const SizedBox(height: 6),
                  Text(t('borderHint'), style: const TextStyle(fontSize: 12, color: kSubtle)),
                  const SizedBox(height: 18),
                  TextButton.icon(
                    style: TextButton.styleFrom(foregroundColor: kDanger),
                    icon: const Icon(Icons.delete_outline),
                    label: Text(t('deleteFarm')),
                    onPressed: _busy ? null : _delete,
                  ),
                ]);
              },
            ),
          ),
        ]),
      ),
    );
  }
}

/// 12.5 -> "12.5", 12.0 -> "12" (for editable fields: no grouping separators).
String fmtPlain(Object? v) {
  final d = (v as num).toDouble();
  return d == d.roundToDouble() ? d.toInt().toString() : d.toString();
}
