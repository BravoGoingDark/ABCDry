import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';
import '../widgets.dart';

/// Water: when and how much, the water in the soil, and what skipping costs.
class WaterTab extends StatefulWidget {
  const WaterTab({super.key, required this.farmId});
  final int farmId;

  @override
  State<WaterTab> createState() => _WaterTabState();
}

class _WaterTabState extends State<WaterTab> {
  Future<dynamic>? _load;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void didUpdateWidget(WaterTab old) {
    super.didUpdateWidget(old);
    if (old.farmId != widget.farmId) _reload();
  }

  void _reload() => setState(() {
        _load = Api.I.get('/farmer/api/farms/${widget.farmId}/irrigation/');
      });

  Future<void> _watered(Map? next) async {
    final todayDose = next != null && next['date'] == todayIso() ? (next['gross_mm'] as num?)?.toDouble() : null;
    final r = await showLogForm(context,
        kind: 'irrigation', amount: todayDose, chooseKind: false, chooseStatus: false, showNote: false);
    if (r == null || !mounted) return;
    if (await changeLog(context, widget.farmId, body: r.body)) _reload();
  }

  Widget _stat(String label, String value) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(fontSize: 12, color: kSubtle)),
        Text(value, style: hl(17, weight: FontWeight.w700)),
      ]);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<dynamic>(
      future: _load,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
        if (snap.hasError) return errorView(snap.error!, _reload);
        final d = Map<String, dynamic>.from(snap.data as Map);
        if (d['available'] != true) {
          return ListView(padding: const EdgeInsets.all(16), children: [
            Card(
                child: ListTile(
                    leading: const Icon(Icons.info_outline),
                    title: Text(t(d['reason'] == 'no_crop' ? 'noCropSet' : 'weatherDown')))),
          ]);
        }
        final now = Map<String, dynamic>.from(d['now'] as Map);
        final next = d['next'] as Map?;
        final events = ((d['events'] as List?) ?? const []).cast<Map>();
        final sc = d['scenarios'] as Map?;
        final code = now['code'] as String;
        final pct = ((now['available_pct'] as num?) ?? 0).clamp(0, 100) / 100;
        final thr = ((now['threshold_pct'] as num?) ?? 0) / 100;
        final stress = ((now['stress_pct'] as num?) ?? 0) / 100;

        return RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(padding: const EdgeInsets.all(14), children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: next == null
                    ? Row(children: [
                        const Icon(Icons.check_circle, color: kLeaf),
                        const SizedBox(width: 10),
                        Expanded(child: Text(code == 'no_crop' ? t('st_no_crop') : t('noWatering16'))),
                      ])
                    : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Row(children: [
                          const Icon(Icons.water_drop, color: kWater, size: 32),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(t('nextWatering').toUpperCase(),
                                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: kSubtle)),
                              Text('${relDay(next['date'] as String)} · ${fmtDate(next['date'] as String)}',
                                  style: hl(19, weight: FontWeight.w800)),
                            ]),
                          ),
                          Chip(
                            label: Text(t('st_$code'), style: const TextStyle(fontSize: 12)),
                            backgroundColor: code == 'stress' ? const Color(0xFFFEE2E2) : kMint,
                          ),
                        ]),
                        const SizedBox(height: 10),
                        Text('${fmtNum(next['gross_mm'], 1)} ${t('mm')}',
                            style: hl(36, weight: FontWeight.w800, color: kWaterDeep)),
                        Text('= L/m²', style: const TextStyle(color: kSubtle)),
                        const SizedBox(height: 10),
                        Wrap(spacing: 24, runSpacing: 8, children: [
                          _stat(t('wholeFarm'), '${fmtNum(next['m3_farm'])} ${t('m3')}'),
                          if (next['hours'] != null) _stat(t('pumpTime'), '${fmtNum(next['hours'], 1)} ${t('h')}'),
                        ]),
                        const SizedBox(height: 10),
                        for (final tip in ((next['tips_text'] as List?) ?? const []))
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              const Icon(Icons.tips_and_updates, size: 16, color: kWarn),
                              const SizedBox(width: 6),
                              Expanded(child: Text('$tip', style: const TextStyle(fontSize: 13))),
                            ]),
                          ),
                      ]),
              ),
            ),
            if (code != 'no_crop')
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(t('soilNow'), style: hl(15, weight: FontWeight.w700)),
                    const SizedBox(height: 22),
                    LayoutBuilder(builder: (context, box) {
                      final w = box.maxWidth;
                      Widget mark(double at, Color c, String label) => PositionedDirectional(
                            start: (at * w).clamp(0, w - 2),
                            top: -18,
                            bottom: -4,
                            child: Column(children: [
                              Text(label, style: TextStyle(fontSize: 10, color: c, fontWeight: FontWeight.w600)),
                              Expanded(child: Container(width: 2, color: c)),
                            ]),
                          );
                      return Directionality(
                        textDirection: TextDirection.ltr,
                        child: SizedBox(
                          height: 26,
                          child: Stack(clipBehavior: Clip.none, children: [
                            ClipRRect(
                              borderRadius: BorderRadius.circular(8),
                              child: LinearProgressIndicator(
                                  value: pct.toDouble(),
                                  minHeight: 26,
                                  color: kWater,
                                  backgroundColor: const Color(0xFFFEE2E2)),
                            ),
                            Positioned.fill(
                              child: Align(
                                alignment: Alignment.centerLeft,
                                child: Padding(
                                  padding: const EdgeInsets.only(left: 10),
                                  child: Text('${fmtNum(now['available_pct'])}%',
                                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
                                ),
                              ),
                            ),
                            mark(thr.toDouble(), const Color(0xFF1D4ED8), t('waterAt')),
                            if ((thr - stress).abs() > 0.12) mark(stress.toDouble(), kDanger, t('suffers')),
                          ]),
                        ),
                      );
                    }),
                  ]),
                ),
              ),
            if (sc != null && d['irrigated'] == true && code != 'no_crop')
              Row(children: [
                Expanded(child: _scenario(t('followPlan'), Map<String, dynamic>.from(sc['follow'] as Map), false)),
                const SizedBox(width: 8),
                Expanded(child: _scenario(t('skipPlan'), Map<String, dynamic>.from(sc['skip'] as Map), true)),
              ]),
            if (events.isNotEmpty) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 14, 4, 6),
                child: Text(t('next16'), style: hl(15, weight: FontWeight.w700)),
              ),
              Card(
                child: Column(children: [
                  for (final e in events)
                    ListTile(
                      dense: true,
                      leading: const Icon(Icons.water_drop_outlined, color: kWater),
                      title: Text('${relDay(e['date'] as String)} · ${fmtDate(e['date'] as String)}'),
                      trailing: Text('${fmtNum(e['gross_mm'], 1)} ${t('mm')} · ${fmtNum(e['m3_farm'])} ${t('m3')}',
                          style: const TextStyle(fontWeight: FontWeight.w600, color: kWater)),
                    ),
                ]),
              ),
            ],
            const SizedBox(height: 12),
            FilledButton.icon(
              icon: const Icon(Icons.water_drop),
              label: Text(t('iWatered')),
              onPressed: () => _watered(next),
            ),
          ]),
        );
      },
    );
  }

  Widget _scenario(String title, Map<String, dynamic> s, bool bad) => Card(
        color: bad ? const Color(0xFFFEF2F2) : Colors.white,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: kPrimary)),
            const SizedBox(height: 6),
            if (!bad) Text('${s['waterings']} ${t('waterings')} · ${fmtNum(s['gross_mm'])} ${t('mm')}'),
            Text('${s['stress_days']} ${t('stressDays')}'),
            Text('${s['yield_risk_pct'] == null ? '—' : '${fmtNum(s['yield_risk_pct'])}%'} ${t('harvestRisk')}',
                style: TextStyle(fontWeight: FontWeight.w600, color: bad ? kDanger : kPrimary)),
          ]),
        ),
      );
}
