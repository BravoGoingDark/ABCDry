import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';

/// Weather at the parcel (16 days) and the field alerts, as the server writes them.
class WeatherTab extends StatefulWidget {
  const WeatherTab({super.key, required this.farmId});
  final int farmId;

  @override
  State<WeatherTab> createState() => _WeatherTabState();
}

class _WeatherTabState extends State<WeatherTab> {
  Future<dynamic>? _load;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void didUpdateWidget(WeatherTab old) {
    super.didUpdateWidget(old);
    if (old.farmId != widget.farmId) _reload();
  }

  void _reload() => setState(() {
        _load = Api.I.get('/farmer/api/farms/${widget.farmId}/weather/');
      });

  static const _levelColor = {'danger': kDanger, 'warning': kWarn, 'info': kLeaf};

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<dynamic>(
      future: _load,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
        if (snap.hasError) return errorView(snap.error!, _reload);
        final fc = (snap.data['forecast'] as Map?) ?? const {};
        final days =
            ((fc['days'] as List?) ?? const []).cast<Map>().where((x) => dayDiff('${x['date']}') >= 0).toList();
        final alerts = ((snap.data['alerts'] as List?) ?? const []).cast<Map>();
        if (fc['error'] != null || days.isEmpty) return errorView(t('weatherDown'), _reload);
        return RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(padding: const EdgeInsets.all(14), children: [
            if (alerts.isNotEmpty) ...[
              Text(t('alerts'), style: hl(15, weight: FontWeight.w700)),
              const SizedBox(height: 6),
              for (final a in alerts)
                Card(
                  child: ListTile(
                    leading: Icon(Icons.warning_amber_rounded, color: _levelColor[a['level']] ?? kLeaf),
                    title: Text('${a['title']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    subtitle: Text('${a['text']}'),
                  ),
                ),
              const SizedBox(height: 10),
            ],
            Card(
              child: Column(children: [
                for (final x in days)
                  ListTile(
                    dense: true,
                    title: Text(dayDiff('${x['date']}') == 0 ? t('today') : shortDay('${x['date']}'),
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    subtitle: Text('${(x['condition'] as Map?)?['label'] ?? ''}'),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text('${fmtNum(x['tmax'])}° / ${fmtNum(x['tmin'])}°', style: hl(15, weight: FontWeight.w700)),
                        Text(
                            '${t('rain')} ${fmtNum(x['precip'] ?? 0, 1)} ${t('mm')}'
                            '${x['precip_prob'] != null ? ' (${x['precip_prob']}%)' : ''} · '
                            '${t('wind')} ${fmtNum(x['wind'])} ${t('kmh')}',
                            style: const TextStyle(fontSize: 12, color: kSubtle)),
                      ],
                    ),
                  ),
              ]),
            ),
          ]),
        );
      },
    );
  }
}
