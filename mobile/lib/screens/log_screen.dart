import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';
import '../widgets.dart';

/// Farm log: everything recorded; anything forgotten can be added on its real
/// date and any entry corrected or deleted. The server replays the log, so
/// the plan follows.
class LogScreen extends StatefulWidget {
  const LogScreen({super.key, required this.farmId});
  final int farmId;

  @override
  State<LogScreen> createState() => _LogScreenState();
}

class _LogScreenState extends State<LogScreen> {
  Future<dynamic>? _load;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() => setState(() {
        _load = Api.I.get('/farmer/api/farms/${widget.farmId}/activities/');
      });

  Future<void> _edit(Map<String, dynamic>? entry) async {
    final r = await showLogForm(context, existing: entry);
    if (r == null || !mounted) return;
    final ok = await changeLog(context, widget.farmId,
        body: r.delete ? null : r.body, id: entry?['id'] as int?, delete: r.delete);
    if (ok) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(t('farmLog'))),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: Text(t('addForgotten')),
        onPressed: () => _edit(null),
      ),
      body: Column(children: [
        offlineBanner(),
        Expanded(
          child: FutureBuilder<dynamic>(
            future: _load,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snap.hasError) return errorView(snap.error!, _reload);
              final items = ((snap.data['activities'] as List?) ?? const []).cast<Map>();
              if (items.isEmpty) {
                return Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(t('logEmpty'))));
              }
              return RefreshIndicator(
                onRefresh: () async => _reload(),
                child: ListView.separated(
                  padding: const EdgeInsets.fromLTRB(0, 8, 0, 96),
                  itemCount: items.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, i) {
                    final x = Map<String, dynamic>.from(items[i]);
                    final parts = [
                      t('k_${x['kind']}'),
                      if (x['amount_mm'] != null) '${fmtNum(x['amount_mm'], 1)} ${t('mm')}',
                      if (x['status'] == 'skipped') t('notDone'),
                    ];
                    return ListTile(
                      leading: Icon(kindIcon(x['kind'] as String?), color: kLeaf),
                      title: Text(parts.join(' · ')),
                      subtitle: Text([fmtDate(x['date'] as String), if ((x['note'] ?? '') != '') x['note']].join('\n')),
                      trailing: const Icon(Icons.edit),
                      onTap: () => _edit(x),
                    );
                  },
                ),
              );
            },
          ),
        ),
      ]),
    );
  }
}
