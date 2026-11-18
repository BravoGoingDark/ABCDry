import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';
import '../widgets.dart';
import 'log_screen.dart';

/// Today: reminders and questions (what, why, how), answered in place.
class TodayTab extends StatefulWidget {
  const TodayTab({super.key, required this.farmId});
  final int farmId;

  @override
  State<TodayTab> createState() => _TodayTabState();
}

class _TodayTabState extends State<TodayTab> {
  Future<dynamic>? _load;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void didUpdateWidget(TodayTab old) {
    super.didUpdateWidget(old);
    if (old.farmId != widget.farmId) _reload();
  }

  void _reload() => setState(() {
        _load = Api.I.get('/farmer/api/farms/${widget.farmId}/tasks/');
      });

  Future<void> _answer(Map<String, dynamic> task, String action) async {
    final a = Map<String, dynamic>.from(task['answer'] as Map);
    final kind = (a['kind'] as String?) ?? task['kind'] as String;
    Map<String, dynamic>? body;
    if (action == 'skip') {
      body = {'kind': kind, 'status': 'skipped', 'date': todayIso()};
    } else if (action == 'quick') {
      body = {
        'kind': kind,
        'status': 'done',
        'date': a['type'] == 'yesno' ? a['date'] : todayIso(),
        'amount_mm': a['type'] == 'irrigation' ? a['dose_mm'] : null,
      };
    } else {
      final r = await showLogForm(context,
          kind: kind,
          date: (a['date'] as String?) ?? todayIso(),
          amount: (a['dose_mm'] as num?)?.toDouble(),
          minDate: a['min_date'] as String?,
          chooseKind: false,
          chooseStatus: false,
          showNote: false);
      if (r == null) return;
      body = r.body;
    }
    body['task_key'] = task['key'];
    if (!mounted) return;
    if (await changeLog(context, widget.farmId, body: body)) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<dynamic>(
      future: _load,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
        if (snap.hasError) return errorView(snap.error!, _reload);
        final tasks = ((snap.data['tasks'] as List?) ?? const []).cast<Map>();
        return RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(padding: const EdgeInsets.all(14), children: [
            if (tasks.isEmpty)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.check_circle, color: kLeaf),
                  title: Text(t('nothingToDo')),
                ),
              ),
            for (final task in tasks)
              TaskCard(
                task: Map<String, dynamic>.from(task),
                onAction: (act) => _answer(Map<String, dynamic>.from(task), act),
              ),
            const SizedBox(height: 6),
            OutlinedButton.icon(
              icon: const Icon(Icons.history),
              label: Text('${t('farmLog')} · ${t('addForgotten')}'),
              onPressed: () async {
                await Navigator.push(context, MaterialPageRoute(builder: (_) => LogScreen(farmId: widget.farmId)));
                _reload();
              },
            ),
          ]),
        );
      },
    );
  }
}
