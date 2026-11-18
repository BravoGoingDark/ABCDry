import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';

class _Msg {
  _Msg(this.text, this.mine, {this.meta = ''});
  final String text;
  final bool mine;
  final String meta;
}

class _Conversation {
  final List<_Msg> msgs = [];
  final List<Map<String, String>> history = [];
  List<dynamic>? farmTopics;
}

/// The conversation with the assistant: answers from the farm's own data (watering, tasks, products,
/// weather...) and says so when it has no information. Same API as the web.
class ChatTab extends StatefulWidget {
  const ChatTab({super.key, required this.farm});
  final Map<String, dynamic> farm;

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  static final Map<int, _Conversation> _byFarm = {}; // kept while the app runs
  final _input = TextEditingController();
  final _scroll = ScrollController();
  List<String> _suggestions = [];
  bool _busy = false;

  int get _farmId => widget.farm['id'] as int;
  _Conversation get _c => _byFarm.putIfAbsent(_farmId, _Conversation.new);

  @override
  void initState() {
    super.initState();
    _loadSuggestions();
  }

  @override
  void didUpdateWidget(ChatTab old) {
    super.didUpdateWidget(old);
    if (old.farm['id'] != widget.farm['id']) _loadSuggestions();
  }

  Future<void> _loadSuggestions() async {
    try {
      final d = await Api.I.get('/assistant/chat/?lang=${appLang.value}&farm=$_farmId');
      if (mounted) setState(() => _suggestions = ((d['suggestions'] as List?) ?? const []).cast<String>());
    } catch (_) {}
  }

  Future<void> _send(String text) async {
    final q = text.trim();
    if (q.isEmpty || _busy) return;
    _input.clear();
    setState(() {
      _c.msgs.add(_Msg(q, true));
      _c.history.add({'role': 'user', 'content': q});
      _busy = true;
    });
    _toBottom();
    try {
      final d = await Api.I.post('/assistant/chat/', {
        'question': q,
        'lang': appLang.value,
        'farm_id': _farmId,
        'region_id': widget.farm['region_id'],
        'crop': widget.farm['crop'],
        'history': _c.history.length > 8 ? _c.history.sublist(_c.history.length - 8) : _c.history,
        'conversation': {
          'crop': widget.farm['crop'],
          'region_name': widget.farm['region'],
          'farm_topics': _c.farmTopics
        },
      });
      final answer = '${d['answer'] ?? '—'}';
      final sources = ((d['sources'] as List?) ?? const []).cast<Map>().map((s) => '${s['title']}').toList();
      final facts = d['facts'] as Map?;
      final meta = d['engine'] == 'farm_data'
          ? sources.join(' · ')
          : facts != null && facts['risk_score'] != null
              ? '${d['region'] ?? ''} · ${facts['risk_score']}/100'
              : '';
      _c.farmTopics = (d['understood'] as Map?)?['farm_topics'] as List?;
      _c.msgs.add(_Msg(answer, false, meta: meta));
      _c.history.add({'role': 'assistant', 'content': answer});
      if (d['suggestions'] is List) _suggestions = (d['suggestions'] as List).cast<String>();
    } on ApiException catch (e) {
      _c.msgs.add(_Msg('${t('chatDown')} (${e.message})', false));
    } finally {
      if (mounted) setState(() => _busy = false);
      _toBottom();
    }
  }

  void _toBottom() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
        }
      });

  Widget _bubble(_Msg m) {
    final rtl = RegExp(r'[؀-ۿ]').hasMatch(m.text);
    final bubble = Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
      constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
      decoration: BoxDecoration(
        color: m.mine ? kPrimary : kSurfaceLow,
        border: m.mine ? null : Border.all(color: kOutlineSoft),
        borderRadius: BorderRadiusDirectional.only(
          topStart: const Radius.circular(16),
          topEnd: const Radius.circular(16),
          bottomStart: Radius.circular(m.mine ? 16 : 4),
          bottomEnd: Radius.circular(m.mine ? 4 : 16),
        ),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(m.text,
            textDirection: rtl ? TextDirection.rtl : TextDirection.ltr,
            style: TextStyle(color: m.mine ? Colors.white : kText, fontSize: 15, height: 1.5)),
        if (m.meta.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(m.meta, style: const TextStyle(fontSize: 11, color: kSecondary, fontWeight: FontWeight.w600)),
        ],
      ]),
    );
    if (m.mine) return Align(alignment: AlignmentDirectional.centerEnd, child: bubble);
    return Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
      const _BotAvatar(),
      const SizedBox(width: 8),
      Flexible(child: bubble),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final msgs = [_Msg(t('hello'), false), ..._c.msgs];
    return Column(children: [
      Expanded(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
          children: [
            for (final m in msgs) _bubble(m),
            if (_busy)
              const Row(children: [
                _BotAvatar(),
                SizedBox(width: 8),
                Padding(
                  padding: EdgeInsets.all(10),
                  child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                ),
              ]),
          ],
        ),
      ),
      if (_suggestions.isNotEmpty)
        SizedBox(
          height: 48,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 4),
            children: [
              for (final s in _suggestions.take(6))
                Padding(
                  padding: const EdgeInsetsDirectional.only(end: 6),
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size(0, 34),
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      shape: const StadiumBorder(),
                      textStyle: const TextStyle(fontFamily: 'Inter', fontSize: 13, fontWeight: FontWeight.w500),
                    ),
                    onPressed: () => _send(s),
                    child: Text(s),
                  ),
                ),
            ],
          ),
        ),
      Container(
        decoration: const BoxDecoration(border: Border(top: BorderSide(color: kOutlineSoft))),
        child: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  textInputAction: TextInputAction.send,
                  onSubmitted: _send,
                  style: const TextStyle(fontSize: 16),
                  decoration: InputDecoration(
                    hintText: t('askPlaceholder'),
                    border: const OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12))),
                    enabledBorder: const OutlineInputBorder(
                        borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: kOutline)),
                    focusedBorder: const OutlineInputBorder(
                        borderRadius: BorderRadius.all(Radius.circular(12)),
                        borderSide: BorderSide(color: kSecondary, width: 2)),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: 48,
                height: 48,
                child: FilledButton(
                  style: FilledButton.styleFrom(padding: EdgeInsets.zero, minimumSize: const Size(48, 48)),
                  onPressed: _busy ? null : () => _send(_input.text),
                  child: Tooltip(message: t('askPlaceholder'), child: const Icon(Icons.send, size: 20)),
                ),
              ),
            ]),
          ),
        ),
      ),
    ]);
  }
}

/// The assistant's round avatar beside its answers (the website's .bot-av).
class _BotAvatar extends StatelessWidget {
  const _BotAvatar();

  @override
  Widget build(BuildContext context) => Container(
        width: 30,
        height: 30,
        margin: const EdgeInsets.only(bottom: 6),
        decoration: const BoxDecoration(color: kPrimaryC, shape: BoxShape.circle),
        child: const Icon(Icons.psychology, size: 17, color: kSecondaryFixed),
      );
}

/// The assistant icon with its "live" dot (the website's .ai-avatar).
class AiAvatar extends StatelessWidget {
  const AiAvatar({super.key, this.size = 24});
  final double size;

  @override
  Widget build(BuildContext context) => Center(
        child: SizedBox(
          width: size + 8,
          height: size + 6,
          child: Stack(alignment: Alignment.center, children: [
            Icon(Icons.psychology, size: size, color: const Color(0xFFB2EBFF)),
            PositionedDirectional(
              top: 0,
              end: 0,
              child: Container(
                width: 9,
                height: 9,
                decoration: const BoxDecoration(color: Color(0xFFB2EBFF), shape: BoxShape.circle),
              ),
            ),
          ]),
        ),
      );
}

/// The assistant full screen, as the website opens it on a phone: a dark
/// green header with the AI Agronomist title, then the conversation.
class AssistantScreen extends StatelessWidget {
  const AssistantScreen({super.key, required this.farm});
  final Map<String, dynamic> farm;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: kPrimary,
        foregroundColor: Colors.white,
        toolbarHeight: 62,
        shape: const Border(bottom: BorderSide(color: Color(0x6669D4F4), width: 2)),
        titleSpacing: 4,
        title: Row(children: [
          const AiAvatar(size: 24),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Row(children: [
                Flexible(
                  child: Text(t('aiTitle'),
                      overflow: TextOverflow.ellipsis, style: hl(15, weight: FontWeight.w700, color: Colors.white)),
                ),
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                  decoration: BoxDecoration(color: kSecondaryFixed, borderRadius: BorderRadius.circular(4)),
                  child: Text(t('aiLive').toUpperCase(),
                      style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: Color(0xFF002114))),
                ),
              ]),
              Text('${t('aiSub')} · ${farm['name']}',
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 11, color: Color(0xFF86AF99), fontWeight: FontWeight.w500)),
            ]),
          ),
        ]),
      ),
      body: Column(children: [offlineBanner(), Expanded(child: ChatTab(farm: farm))]),
    );
  }
}
