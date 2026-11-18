import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';
import 'farm_settings_screen.dart';

/// Crop name in the app language (the server sends en / fr / ar).
String cropName(Object? names, [String? fallback]) {
  if (names is Map) return '${names[appLang.value] ?? names['en'] ?? fallback ?? ''}';
  return fallback ?? '';
}

String monthName(int m) => DateFormat.MMMM(appLang.value).format(DateTime(2000, m));

/// Crop: the farm's crop calendar, fertiliser and protection plan, and which
/// crops grow best on this parcel.
class CropTab extends StatefulWidget {
  const CropTab({super.key, required this.farm, required this.onFarmChanged});
  final Map<String, dynamic> farm;

  /// Called after the farm settings were saved or the farm deleted.
  final VoidCallback onFarmChanged;

  @override
  State<CropTab> createState() => _CropTabState();
}

class _CropTabState extends State<CropTab> {
  Future<dynamic>? _plan;
  Future<dynamic>? _advice;

  int get _id => widget.farm['id'] as int;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() => setState(() {
        _plan = widget.farm['crop'] != null ? Api.I.get('/farmer/api/farms/$_id/crop-plan/') : null;
        if (_advice != null || widget.farm['crop'] == null) _advice = Api.I.get('/farmer/api/farms/$_id/advice/');
      });

  Future<void> _settings({String? crop}) async {
    final changed = await Navigator.push<bool>(
        context, MaterialPageRoute(builder: (_) => FarmSettingsScreen(farm: widget.farm, initialCrop: crop)));
    if (changed == true) widget.onFarmChanged();
  }

  void _preview(Map<String, dynamic> crop) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => CropPreviewScreen(
          farmId: _id,
          crop: crop,
          onGrow: () {
            Navigator.pop(context);
            _settings(crop: crop['crop'] as String);
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final farm = widget.farm;
    final hasCrop = farm['crop'] != null;
    return RefreshIndicator(
      onRefresh: () async => _reload(),
      child: ListView(padding: const EdgeInsets.all(14), children: [
        _header(farm),
        if (!hasCrop)
          Card(
            color: kWarnBg,
            child: ListTile(
              leading: const Icon(Icons.info_outline, color: kWarn),
              title: Text(t('setCropFirst')),
            ),
          ),
        if (_plan != null)
          FutureBuilder<dynamic>(
            future: _plan,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()));
              }
              if (snap.hasError) return errorView(snap.error!, _reload);
              return CropPlanView(plan: Map<String, dynamic>.from(snap.data as Map));
            },
          ),
        const SizedBox(height: 8),
        _bestCrops(),
      ]),
    );
  }

  Widget _header(Map<String, dynamic> farm) {
    final sowing = farm['sowing_date'] as String?;
    final details = [
      '${fmtNum(farm['area_ha'], 2)} ${t('ha')}',
      t(farm['irrigated'] == true ? 'irrigated' : 'rainfed'),
      if (sowing != null) '${t('sownOn')} ${fmtDate(sowing)}',
    ];
    return Card(
      child: ListTile(
        leading: const CircleAvatar(backgroundColor: kMint, child: Icon(Icons.grass, color: kLeaf)),
        title: Text(
          farm['crop'] != null ? cropName(farm['crop_names'], '${farm['crop_name'] ?? farm['crop']}') : t('noCrop'),
          style: hl(17, weight: FontWeight.w700),
        ),
        subtitle: Text(details.join(' · ')),
        trailing:
            TextButton(onPressed: () => _settings(), child: Text(t(farm['crop'] != null ? 'change' : 'chooseCrop'))),
      ),
    );
  }

  Widget _bestCrops() {
    if (_advice == null) {
      return OutlinedButton.icon(
        icon: const Icon(Icons.eco_outlined),
        label: Text(t('showBest')),
        onPressed: () => setState(() {
          _advice = Api.I.get('/farmer/api/farms/$_id/advice/');
        }),
      );
    }
    return FutureBuilder<dynamic>(
      future: _advice,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()));
        }
        if (snap.hasError) {
          return errorView(
              snap.error!,
              () => setState(() {
                    _advice = Api.I.get('/farmer/api/farms/$_id/advice/');
                  }));
        }
        final d = Map<String, dynamic>.from(snap.data as Map);
        final ranking = ((d['ranking'] as List?) ?? const []).cast<Map>().take(10).toList();
        final notes = ((d['notes'] as List?) ?? const []);
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          sectionTitle(t('bestCrops'), Icons.eco),
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
            child: Text(t(d['mode'] == 'irrigated' ? 'bestCropsIrrigated' : 'bestCropsRainfed'),
                style: const TextStyle(fontSize: 13, color: kSubtle)),
          ),
          for (final n in notes)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Icon(Icons.info_outline, size: 16, color: kWarn),
                const SizedBox(width: 6),
                Expanded(child: Text('$n', style: const TextStyle(fontSize: 12.5, color: kWarn))),
              ]),
            ),
          Card(
            child: Column(children: [
              for (final r in ranking) _rankTile(Map<String, dynamic>.from(r)),
            ]),
          ),
        ]);
      },
    );
  }

  Widget _rankTile(Map<String, dynamic> r) {
    final cls = '${r['class']}';
    final when = r['perennial'] == true
        ? t('perennial')
        : r['plantable_now'] == true
            ? t('sowNow')
            : r['next_planting_month'] != null
                ? t('sowIn', {'m': monthName(r['next_planting_month'] as int)})
                : '';
    final limit = r['limiting_factor'] as String?;
    return ListTile(
      leading: classBadge(cls),
      title: Text(cropName(r['names'], '${r['crop']}'), style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text([
        t('cls_$cls'),
        if (when.isNotEmpty) when,
        if (limit != null) t('limitedBy', {'f': t('f_$limit')}),
      ].join(' · ')),
      trailing: r['crop'] == widget.farm['crop']
          ? const Icon(Icons.check_circle, color: kLeaf)
          : const Icon(Icons.chevron_right),
      onTap: () => _preview(r),
    );
  }
}

Widget classBadge(String cls) {
  const colors = {'S1': kLeaf, 'S2': Color(0xFF65A30D), 'S3': kWarn, 'N': kDanger};
  final c = colors[cls] ?? kSubtle;
  return CircleAvatar(
    radius: 18,
    backgroundColor: c.withValues(alpha: 0.12),
    child: Text(cls, style: TextStyle(color: c, fontWeight: FontWeight.w800, fontSize: 13)),
  );
}

Widget sectionTitle(String text, IconData icon) => Padding(
      padding: const EdgeInsets.fromLTRB(4, 14, 4, 6),
      child: Row(children: [
        Icon(icon, size: 18, color: kLeaf),
        const SizedBox(width: 6),
        Expanded(child: Text(text, style: hl(15, weight: FontWeight.w700))),
      ]),
    );

/// The plan for one crop: calendar, fertiliser, protection.
class CropPlanView extends StatelessWidget {
  const CropPlanView({super.key, required this.plan});
  final Map<String, dynamic> plan;

  static const _eventIcon = {'stage': Icons.grass, 'fertilizer': Icons.science, 'protection': Icons.bug_report};
  static const _eventColor = {'stage': kLeaf, 'fertilizer': Color(0xFF7C3AED), 'protection': kWarn};

  @override
  Widget build(BuildContext context) {
    final events = ((plan['calendar'] as Map?)?['events'] as List? ?? const []).cast<Map>();
    final fert = plan['fertilizer'] as Map?;
    final protection = ((plan['protection'] as List?) ?? const []).cast<Map>();
    // Recent past (a month) stays visible, older steps are hidden.
    final shown = events.where((e) => dayDiff('${e['date']}') >= -30).toList();

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (shown.isNotEmpty) ...[
        sectionTitle(t('calendar'), Icons.event_note),
        Card(
          child: Column(children: [
            for (final e in shown) _event(Map<String, dynamic>.from(e)),
          ]),
        ),
      ],
      if (fert != null) ...[
        sectionTitle(t('fertilizer'), Icons.science),
        _fertilizer(Map<String, dynamic>.from(fert)),
      ],
      if (protection.isNotEmpty) ...[
        sectionTitle(t('protection'), Icons.bug_report),
        for (final p in protection) _threat(context, Map<String, dynamic>.from(p)),
        if ((plan['protection_notice'] ?? '') != '') _notice('${plan['protection_notice']}'),
      ],
    ]);
  }

  Widget _notice(String text) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 4, 8),
        child: Text(text, style: const TextStyle(fontSize: 12, color: kSubtle, fontStyle: FontStyle.italic)),
      );

  Widget _event(Map<String, dynamic> e) {
    final date = '${e['date']}';
    final past = dayDiff(date) < 0;
    final kind = '${e['kind']}';
    final color = past ? kOutline : (_eventColor[kind] ?? kLeaf);
    return ListTile(
      dense: true,
      leading: Icon(past ? Icons.check_circle_outline : (_eventIcon[kind] ?? Icons.event), color: color),
      title: Text('${e['title']}', style: TextStyle(fontWeight: FontWeight.w600, color: past ? kSubtle : kPrimary)),
      subtitle: Text([
        '${fmtDate(date)}${past ? '' : ' · ${relDay(date)}'}',
        if ((e['detail'] ?? '') != '') '${e['detail']}',
      ].join('\n')),
      isThreeLine: (e['detail'] ?? '') != '',
    );
  }

  Widget _fertilizer(Map<String, dynamic> fert) {
    final totals = (fert['totals'] as Map?) ?? const {};
    final schedule = ((fert['schedule'] as List?) ?? const []).cast<Map>();
    String range(Object? v) =>
        v is List && v.length == 2 ? (v[0] == v[1] ? fmtNum(v[0]) : '${fmtNum(v[0])}–${fmtNum(v[1])}') : fmtNum(v);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (totals.isNotEmpty) ...[
            Text(t('seasonTotal'), style: const TextStyle(fontSize: 12, color: kSubtle)),
            const SizedBox(height: 4),
            Wrap(spacing: 8, runSpacing: 6, children: [
              for (final k in totals.keys)
                Chip(
                  visualDensity: VisualDensity.compact,
                  backgroundColor: kMint,
                  label: Text('$k ${range(totals[k])} ${t('kgHa')}', style: const TextStyle(fontSize: 12)),
                ),
            ]),
          ],
          for (final s in schedule) _application(Map<String, dynamic>.from(s)),
          if ((fert['note'] ?? '') != '') ...[
            const SizedBox(height: 8),
            Text('${fert['note']}', style: const TextStyle(fontSize: 12.5, color: kSubtle)),
          ],
          if ((plan['fertilizer_notice'] ?? '') != '') ...[
            const SizedBox(height: 6),
            Text('${plan['fertilizer_notice']}',
                style: const TextStyle(fontSize: 12, color: kSubtle, fontStyle: FontStyle.italic)),
          ],
        ]),
      ),
    );
  }

  Widget _application(Map<String, dynamic> s) {
    final details = (s['details'] as Map?) ?? const {};
    final farm = details['farm'] as Map?;
    final alt = details['alternative'] as Map?;
    final when = s['month'] != null
        ? monthName(s['month'] as int)
        : s['offset_days'] == 0
            ? t('atSowing')
            : t('daysAfterSowing', {'n': s['offset_days']});
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Icon(Icons.science_outlined, size: 20, color: Color(0xFF7C3AED)),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${s['stage']}', style: hl(15, weight: FontWeight.w700)),
            Text(when, style: const TextStyle(fontSize: 12, color: kSubtle)),
            const SizedBox(height: 2),
            Text('${s['product']} · ${s['rate']}'),
            if (farm != null)
              Text(
                t('forFarm', {
                  'ha': fmtNum(farm['area_ha'], 2),
                  'kg': farm['kg'],
                  'bags': farm['bags'],
                  'bag': fmtNum(farm['bag_kg']),
                }),
                style: const TextStyle(fontWeight: FontWeight.w700, color: kLeaf),
              ),
            if (alt != null)
              Text(
                '${t('orUse')} ${alt['name']} · ${alt['rate']}'
                '${alt['farm_kg'] != null ? ' (${alt['farm_kg']} kg)' : ''}',
                style: const TextStyle(fontSize: 12.5, color: kSubtle),
              ),
          ]),
        ),
      ]),
    );
  }

  Widget _threat(BuildContext context, Map<String, dynamic> p) {
    final months = ((p['months'] as List?) ?? const []).cast<int>();
    final products = ((p['products'] as List?) ?? const []).cast<Map>();
    final isNow = months.contains(DateTime.now().month);
    Widget line(String label, Object? text) => (text ?? '') == ''
        ? const SizedBox.shrink()
        : Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label.toUpperCase(),
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: kSubtle)),
              Text('$text', style: const TextStyle(fontSize: 13.5)),
            ]),
          );
    return Card(
      color: isNow ? const Color(0xFFFFFBEB) : Colors.white,
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          leading: Icon(Icons.bug_report, color: isNow ? kWarn : kSubtle),
          title: Text('${p['name']}', style: hl(15, weight: FontWeight.w700)),
          subtitle: Text(
            [
              if (isNow) t('riskNow'),
              if (months.isNotEmpty && months.length < 12) months.map(monthName).join(', '),
            ].join(' · '),
            style: TextStyle(fontSize: 12, color: isNow ? kWarn : kSubtle),
          ),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          children: [
            line(t('watchFor'), p['watch']),
            line(t('prevent'), p['prevent']),
            line(t('treat'), p['control']),
            if (products.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(t('products').toUpperCase(),
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: kSubtle)),
              for (final o in products)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Icon(_kindIcon[o['kind']] ?? Icons.circle, size: 16, color: kLeaf),
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        [
                          '${o['name']}${(o['group'] ?? '') != '' ? ' (${o['group']})' : ''}',
                          if ((o['rate'] ?? '') != '') '${o['rate']}',
                          if (o['farm'] != null) '→ ${o['farm']}',
                          if ((o['notes'] ?? '') != '') '${o['notes']}',
                        ].join(' · '),
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                  ]),
                ),
            ],
          ],
        ),
      ),
    );
  }

  static const _kindIcon = {
    'cultural': Icons.agriculture,
    'trap': Icons.filter_alt,
    'biological': Icons.eco,
    'mineral': Icons.landscape,
    'chemical': Icons.sanitizer,
  };
}

/// Plan for a crop the farmer is considering, sized for this farm.
class CropPreviewScreen extends StatefulWidget {
  const CropPreviewScreen({super.key, required this.farmId, required this.crop, required this.onGrow});
  final int farmId;
  final Map<String, dynamic> crop;
  final VoidCallback onGrow;

  @override
  State<CropPreviewScreen> createState() => _CropPreviewScreenState();
}

class _CropPreviewScreenState extends State<CropPreviewScreen> {
  Future<dynamic>? _plan;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() => setState(() {
        _plan = Api.I.get(
            '/farmer/api/farms/${widget.farmId}/crop-plan/?crop=${Uri.encodeQueryComponent('${widget.crop['crop']}')}');
      });

  @override
  Widget build(BuildContext context) {
    final c = widget.crop;
    final cls = '${c['class']}';
    final wb = (c['water_balance'] as Map?) ?? const {};
    return Scaffold(
      appBar: AppBar(title: Text(cropName(c['names'], '${c['crop']}'))),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 6, 14, 10),
          child: FilledButton.icon(icon: const Icon(Icons.grass), label: Text(t('growThis')), onPressed: widget.onGrow),
        ),
      ),
      body: Column(children: [
        offlineBanner(),
        Expanded(
          child: ListView(padding: const EdgeInsets.all(14), children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Row(children: [
                  classBadge(cls),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${t('cls_$cls')} · ${fmtNum(c['score'])}/100', style: hl(15, weight: FontWeight.w700)),
                      if (wb['etc_mm'] != null)
                        Text(t('cropWater', {'mm': fmtNum(wb['etc_mm'])}), style: const TextStyle(fontSize: 13)),
                      if ((wb['gross_irrigation_mm'] ?? 0) as num > 0)
                        Text(t('irrigationNeed', {'mm': fmtNum(wb['gross_irrigation_mm'])}),
                            style: const TextStyle(fontSize: 13, color: kWater)),
                    ]),
                  ),
                ]),
              ),
            ),
            FutureBuilder<dynamic>(
              future: _plan,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()));
                }
                if (snap.hasError) return errorView(snap.error!, _reload);
                return CropPlanView(plan: Map<String, dynamic>.from(snap.data as Map));
              },
            ),
          ]),
        ),
      ]),
    );
  }
}
