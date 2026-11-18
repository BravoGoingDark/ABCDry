import 'package:material_ui/material_ui.dart';

import 'api.dart';
import 'format.dart';
import 'i18n.dart';

const logKinds = ['irrigation', 'fertilizer', 'treatment', 'scouting', 'sowing', 'harvest', 'other'];

Future<String?> _nextWatering(int farmId) async {
  try {
    final d = await Api.I.get('/farmer/api/farms/$farmId/irrigation/');
    return d['available'] == true && d['next'] != null ? d['next']['date'] as String : null;
  } catch (_) {
    return null;
  }
}

/// Add, correct or delete a log entry, then say how the plan moved.
/// Returns true when the server accepted the change.
Future<bool> changeLog(BuildContext context, int farmId,
    {Map<String, dynamic>? body, int? id, bool delete = false}) async {
  final before = await _nextWatering(farmId);
  try {
    final path = '/farmer/api/farms/$farmId/activities/${id != null ? '$id/' : ''}';
    if (delete) {
      await Api.I.delete(path);
    } else if (id != null) {
      await Api.I.patch(path, body!);
    } else {
      await Api.I.post(path, body);
    }
  } on ApiException catch (e) {
    if (context.mounted) showMessage(context, e.message, error: true);
    return false;
  }
  final after = await _nextWatering(farmId);
  var msg = t('saved');
  if (before != after) {
    msg = after == null
        ? t('planNone')
        : before == null
            ? t('planNew', {'b': fmtDate(after)})
            : t('planMoved', {'a': fmtDate(before), 'b': fmtDate(after)});
  }
  if (context.mounted) showMessage(context, msg);
  return true;
}

/// Result of the log form: the fields to send, or a delete request.
class LogFormResult {
  LogFormResult(this.body, {this.delete = false});
  final Map<String, dynamic> body;
  final bool delete;
}

/// One form for every log entry: task answers, "I watered", the farm log.
Future<LogFormResult?> showLogForm(
  BuildContext context, {
  Map<String, dynamic>? existing,
  String kind = 'irrigation',
  String? date,
  double? amount,
  String? minDate,
  bool chooseKind = true,
  bool chooseStatus = true,
  bool showNote = true,
}) {
  var k = (existing?['kind'] as String?) ?? kind;
  var status = (existing?['status'] as String?) ?? 'done';
  var day = (existing?['date'] as String?) ?? date ?? todayIso();
  final amountCtl = TextEditingController(
      text: existing != null
          ? (existing['amount_mm'] != null ? fmtNum(existing['amount_mm'], 1) : '')
          : (amount != null ? fmtNum(amount, 1) : ''));
  final noteCtl = TextEditingController(text: (existing?['note'] as String?) ?? '');
  final first = minDate != null ? parseDay(minDate) : DateTime.now().subtract(const Duration(days: 365));

  return showDialog<LogFormResult>(
    context: context,
    builder: (context) => StatefulBuilder(builder: (context, setState) {
      final showAmount = k == 'irrigation' && status == 'done';
      return AlertDialog(
        scrollable: true,
        title: Text(existing != null ? t('farmLog') : t(chooseKind ? 'addForgotten' : 'k_$k')),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (chooseKind) ...[
            Text(t('whatDid')),
            const SizedBox(height: 6),
            DropdownButtonFormField<String>(
              initialValue: k,
              items: [for (final x in logKinds) DropdownMenuItem(value: x, child: Text(t('k_$x')))],
              onChanged: (v) => setState(() => k = v ?? k),
            ),
            const SizedBox(height: 12),
          ],
          if (chooseStatus) ...[
            SegmentedButton<String>(
              segments: [
                ButtonSegment(value: 'done', label: Text(t('didIt')), icon: const Icon(Icons.check_circle)),
                ButtonSegment(value: 'skipped', label: Text(t('didNot')), icon: const Icon(Icons.cancel)),
              ],
              selected: {status},
              onSelectionChanged: (v) => setState(() => status = v.first),
            ),
            const SizedBox(height: 12),
          ],
          Text(t('when')),
          const SizedBox(height: 6),
          OutlinedButton.icon(
            icon: const Icon(Icons.event),
            label: Text(fmtDate(day)),
            onPressed: () async {
              final picked = await showDatePicker(
                context: context,
                initialDate: parseDay(day).isBefore(first) ? first : parseDay(day),
                firstDate: first,
                lastDate: DateTime.now(),
              );
              if (picked != null) setState(() => day = isoDay(picked));
            },
          ),
          if (showAmount) ...[
            const SizedBox(height: 12),
            TextField(
              controller: amountCtl,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(labelText: t('amount'), suffixText: t('mm')),
            ),
          ],
          if (showNote) ...[
            const SizedBox(height: 12),
            TextField(controller: noteCtl, maxLength: 200, decoration: InputDecoration(labelText: t('note'))),
          ],
        ]),
        actions: [
          if (existing != null)
            TextButton(
              style: TextButton.styleFrom(foregroundColor: kDanger),
              onPressed: () async {
                final ok = await showDialog<bool>(
                  context: context,
                  builder: (c) => AlertDialog(
                    content: Text(t('deleteConfirm')),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t('cancel'))),
                      FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t('delete'))),
                    ],
                  ),
                );
                if (ok == true && context.mounted) Navigator.pop(context, LogFormResult(const {}, delete: true));
              },
              child: Text(t('delete')),
            ),
          TextButton(onPressed: () => Navigator.pop(context), child: Text(t('cancel'))),
          FilledButton(
            onPressed: () {
              final mm = double.tryParse(amountCtl.text.replaceAll(',', '.').trim());
              Navigator.pop(
                  context,
                  LogFormResult({
                    'kind': k,
                    'status': status,
                    'date': day,
                    'amount_mm': showAmount ? mm : null,
                    'note': noteCtl.text.trim(),
                  }));
            },
            child: Text(t('save')),
          ),
        ],
      );
    }),
  );
}

const _kindIcon = {
  'irrigation': Icons.water_drop,
  'fertilizer': Icons.science,
  'scouting': Icons.search,
  'sowing': Icons.grass,
  'harvest': Icons.agriculture,
  'treatment': Icons.sanitizer,
  'other': Icons.edit_note,
};

IconData kindIcon(String? kind) => _kindIcon[kind] ?? Icons.task_alt;

/// A reminder or question: what, why, how, and the answer buttons.
class TaskCard extends StatelessWidget {
  const TaskCard({super.key, required this.task, required this.onAction});
  final Map<String, dynamic> task;
  final void Function(String action) onAction;

  @override
  Widget build(BuildContext context) {
    final text = Map<String, dynamic>.from(task['text'] as Map? ?? {});
    final state = task['state'] as String;
    final late = -dayDiff(task['date'] as String);
    final when = state == 'ask'
        ? t('question') + (late > 0 && task['kind'] != 'sowing' ? ' · ${t('daysLate', {'n': late})}' : '')
        : state == 'today'
            ? t('today')
            : '${t('soon')} · ${relDay(task['date'] as String)}';
    final accent = state == 'ask'
        ? const Color(0xFFF59E0B)
        : state == 'today'
            ? kWater
            : kOk;
    final answer = task['answer'] as Map?;
    final products = (task['products'] as List?) ?? const [];

    Widget lines(String label, List items, IconData icon, Color iconColor) => items.isEmpty
        ? const SizedBox.shrink()
        : Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label.toUpperCase(), style: kCapsLabel),
              for (final x in items)
                Padding(
                  padding: const EdgeInsets.only(top: 5),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Padding(padding: const EdgeInsets.only(top: 1), child: Icon(icon, size: 16, color: iconColor)),
                    const SizedBox(width: 6),
                    Expanded(child: Text('$x', style: const TextStyle(fontSize: 13.5, color: kMuted, height: 1.4))),
                  ]),
                ),
            ]),
          );

    final buttons = <Widget>[];
    void add(String label, String action, {bool primary = true}) => buttons.add(primary
        ? FilledButton(onPressed: () => onAction(action), child: Text(label))
        : OutlinedButton(onPressed: () => onAction(action), child: Text(label)));
    switch (answer?['type']) {
      case 'irrigation':
        if (answer!['only_today'] == true) {
          add(t('doneDose', {'mm': fmtNum(answer['dose_mm'], 1)}), 'quick');
          add(t('otherAmount'), 'form', primary: false);
          add(t('notToday'), 'skip', primary: false);
        } else {
          add(t('yesWatered'), 'form');
          if (answer['no_skip'] != true) add(t('notYet'), 'skip', primary: false);
        }
      case 'yesno':
        add(t('yesDone'), 'quick');
        add(t('no'), 'skip', primary: false);
      case 'done':
        add(t('done'), 'quick');
      case 'checked':
        add(t('checked'), 'quick');
        add(t('hide'), 'skip', primary: false);
      case 'date':
        if (state == 'ask') {
          add(t('yes'), 'form');
          add(t('notYet'), 'skip', primary: false);
        } else {
          add(t('done'), 'form');
        }
    }

    // The website's .tk card: soft border, a 4 px colour stripe on the start side.
    return Card(
      color: state == 'ask' ? const Color(0xFFFFFBEB) : Colors.white,
      margin: const EdgeInsets.only(bottom: 10),
      clipBehavior: Clip.antiAlias,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(16)), side: BorderSide(color: kOutlineSoft)),
      child: Stack(children: [
        PositionedDirectional(start: 0, top: 0, bottom: 0, width: 4, child: ColoredBox(color: accent)),
        Padding(
          padding: const EdgeInsetsDirectional.fromSTEB(18, 14, 16, 14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(kindIcon(task['kind'] as String?), color: kLeaf, size: 24),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(when.toUpperCase(), style: kCapsLabel),
                  const SizedBox(height: 2),
                  Text('${text['title'] ?? ''}', style: hl(16, weight: FontWeight.w700)),
                ]),
              ),
            ]),
            lines(t('why'), (text['why'] as List?) ?? const [], Icons.help_outline, kSubtle),
            lines(t('how'), (text['how'] as List?) ?? const [], Icons.arrow_forward, kWater),
            if (products.isNotEmpty)
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  leading: const Icon(Icons.medication, color: kLeaf),
                  title: Text('${t('products')} (${products.length})',
                      style: const TextStyle(color: kLeaf, fontWeight: FontWeight.w600, fontSize: 14)),
                  children: [
                    for (final p in products.cast<Map>())
                      ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        title: Text('${p['name']}${(p['group'] ?? '') != '' ? ' (${p['group']})' : ''}'),
                        subtitle: Text([
                          if ((p['rate'] ?? '') != '') p['rate'],
                          if (p['farm'] != null) '→ ${p['farm']}',
                          if ((p['notes'] ?? '') != '') p['notes'],
                        ].join('\n')),
                      ),
                  ],
                ),
              ),
            if (buttons.isNotEmpty) ...[
              const SizedBox(height: 12),
              Wrap(spacing: 8, runSpacing: 8, children: buttons),
            ],
          ]),
        ),
      ]),
    );
  }
}
