import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../format.dart';
import '../i18n.dart';
import 'boundary_screen.dart';
import 'chat_tab.dart';
import 'crop_tab.dart';
import 'farm_settings_screen.dart';
import 'log_screen.dart';
import 'today_tab.dart';
import 'water_tab.dart';
import 'weather_tab.dart';

/// The farmer space, laid out like the website's (farmer_home.html on a
/// phone): white header with the logo, language switch and account; the farms
/// as pills; the farm title; the tabs as a bottom bar; the AI Agronomist button.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.onSignedOut, this.initialFarms});
  final VoidCallback onSignedOut;

  /// The farm list already requested behind the loading screen, if any.
  final Future<dynamic>? initialFarms;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Future<dynamic>? _farms;
  int? _farmId;
  int _tab = 0;

  /// Bumped after the farm settings change, so every tab reloads.
  int _rev = 0;

  @override
  void initState() {
    super.initState();
    _farmId = Api.I.prefs?.getInt('farm');
    _farms = widget.initialFarms ?? Api.I.get('/farmer/api/farms/');
  }

  Future<void> _pickFarm(int id) async {
    await Api.I.prefs?.setInt('farm', id);
    setState(() => _farmId = id);
  }

  /// After the farm was edited or deleted: reload the list and every tab.
  void _farmChanged() => setState(() {
        _rev++;
        _farms = Api.I.get('/farmer/api/farms/');
      });

  Future<void> _openSettings(Map<String, dynamic> farm) async {
    final changed =
        await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => FarmSettingsScreen(farm: farm)));
    if (changed == true) _farmChanged();
  }

  /// Mark a new farm on the map, switch to it, then ask what it grows.
  Future<void> _addFarm() async {
    final farm =
        await Navigator.push<Map<String, dynamic>>(context, MaterialPageRoute(builder: (_) => const BoundaryScreen()));
    if (farm == null || !mounted) return;
    await _pickFarm(farm['id'] as int);
    _farmChanged();
    if (mounted) await _openSettings(farm);
  }

  Future<void> _setLang(String value) async {
    await Api.I.setLang(value);
    appLang.value = value; // main.dart rebuilds the app in the new language
  }

  Future<void> _account(String value, Map<String, dynamic>? farm) async {
    if (value == 'settings' && farm != null) {
      await _openSettings(farm);
    } else if (value == 'log' && _farmId != null) {
      await Navigator.push(context, MaterialPageRoute(builder: (_) => LogScreen(farmId: _farmId!)));
    } else if (value == 'add') {
      await _addFarm();
    } else if (value == 'logout') {
      await Api.I.logout();
      widget.onSignedOut();
    }
  }

  void _openAssistant(Map<String, dynamic> farm) =>
      Navigator.push(context, MaterialPageRoute(builder: (_) => AssistantScreen(farm: farm)));

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<dynamic>(
      future: _farms,
      builder: (context, snap) {
        final farms = snap.hasData ? ((snap.data['farms'] as List?) ?? const []).cast<Map>() : <Map>[];
        Map<String, dynamic>? farm;
        if (farms.isNotEmpty) {
          farm = Map<String, dynamic>.from(farms.firstWhere((f) => f['id'] == _farmId, orElse: () => farms.first));
        }
        final id = farm?['id'] as int?;

        Widget body;
        if (snap.connectionState != ConnectionState.done) {
          body = const Center(child: CircularProgressIndicator());
        } else if (snap.hasError) {
          body = errorView(
              snap.error!,
              () => setState(() {
                    _farms = Api.I.get('/farmer/api/farms/');
                  }));
        } else if (farm == null) {
          body = _noFarm();
        } else {
          final k = '$id-$_rev';
          body = Column(children: [
            _FarmPills(farms: farms, selected: id!, onPick: _pickFarm, onAdd: _addFarm),
            _FarmTitle(farm: farm, onEdit: () => _openSettings(farm!)),
            Expanded(
              child: IndexedStack(index: _tab, children: [
                TodayTab(key: ValueKey('today$k'), farmId: id),
                WaterTab(key: ValueKey('water$k'), farmId: id),
                CropTab(key: ValueKey('crop$k'), farm: farm, onFarmChanged: _farmChanged),
                WeatherTab(key: ValueKey('weather$k'), farmId: id),
              ]),
            ),
          ]);
        }

        return PopScope(
          // Android back: go back to Today before leaving the app
          canPop: _tab == 0,
          onPopInvokedWithResult: (didPop, _) {
            if (!didPop) setState(() => _tab = 0);
          },
          child: Scaffold(
            appBar: AppBar(
              toolbarHeight: 64,
              titleSpacing: 16,
              title: Row(children: [
                const BrandLogo(size: 38),
                const SizedBox(width: 12),
                Flexible(
                  child:
                      Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text('APWRS', style: hl(17)),
                    Text(t('farmerSpace'),
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 11, color: kSubtle, fontWeight: FontWeight.w500)),
                  ]),
                ),
              ]),
              actions: [
                LangPill(onPick: _setLang),
                const SizedBox(width: 6),
                _AccountButton(hasFarm: farm != null, onPick: (v) => _account(v, farm)),
                const SizedBox(width: 10),
              ],
            ),
            body: Column(children: [offlineBanner(), Expanded(child: body)]),
            floatingActionButton: farm == null ? null : _AiButton(onTap: () => _openAssistant(farm!)),
            bottomNavigationBar: farm == null ? null : _bottomBar(),
          ),
        );
      },
    );
  }

  Widget _noFarm() => Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Container(
              width: 76,
              height: 76,
              decoration: const BoxDecoration(color: kMint, shape: BoxShape.circle),
              child: const Icon(Icons.agriculture, size: 40, color: kLeaf),
            ),
            const SizedBox(height: 16),
            Text(t('myFarms'), style: hl(22)),
            const SizedBox(height: 8),
            Text(t('noFarm'), textAlign: TextAlign.center, style: const TextStyle(color: kMuted, height: 1.45)),
            const SizedBox(height: 20),
            FilledButton.icon(
              style: FilledButton.styleFrom(
                minimumSize: const Size(0, 50),
                shape: const RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(12))),
              ),
              icon: const Icon(Icons.draw_outlined),
              label: Text(t('addFarm')),
              onPressed: _addFarm,
            ),
          ]),
        ),
      );

  /// The website's phone tab bar: white, rounded on top, soft shadow, the
  /// active icon on a mint pill.
  Widget _bottomBar() => Container(
        decoration: const BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
          border: Border(top: BorderSide(color: kOutlineSoft)),
          boxShadow: [BoxShadow(color: Color(0x1A012D1D), blurRadius: 20, offset: Offset(0, -4))],
        ),
        child: NavigationBar(
          selectedIndex: _tab,
          onDestinationSelected: (i) => setState(() => _tab = i),
          destinations: [
            NavigationDestination(
                icon: const Icon(Icons.home_outlined), selectedIcon: const Icon(Icons.home), label: t('today')),
            NavigationDestination(
                icon: const Icon(Icons.water_drop_outlined),
                selectedIcon: const Icon(Icons.water_drop),
                label: t('water')),
            NavigationDestination(
                icon: const Icon(Icons.eco_outlined), selectedIcon: const Icon(Icons.eco), label: t('crop')),
            NavigationDestination(
                icon: const Icon(Icons.wb_cloudy_outlined),
                selectedIcon: const Icon(Icons.wb_cloudy),
                label: t('weather')),
          ],
        ),
      );
}

/// The farms as pills (the website's .farm-card): the chosen one dark green,
/// "add" with a green outline.
class _FarmPills extends StatelessWidget {
  const _FarmPills({required this.farms, required this.selected, required this.onPick, required this.onAdd});
  final List<Map> farms;
  final int selected;
  final ValueChanged<int> onPick;
  final VoidCallback onAdd;

  Widget _pill(
          {required bool on,
          required Widget icon,
          required String label,
          required VoidCallback onTap,
          bool add = false}) =>
      Padding(
        padding: const EdgeInsetsDirectional.only(end: 8),
        child: Material(
          color: on ? kPrimary : (add ? Colors.transparent : Colors.white),
          shape: StadiumBorder(side: BorderSide(color: on ? kPrimary : (add ? kLeaf : kOutlineSoft))),
          child: InkWell(
            customBorder: const StadiumBorder(),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsetsDirectional.fromSTEB(6, 5, 14, 5),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: on ? Colors.white.withValues(alpha: 0.16) : (add ? kMint : kSurfaceLow),
                  ),
                  child: IconTheme(data: IconThemeData(size: 17, color: on ? Colors.white : kLeaf), child: icon),
                ),
                const SizedBox(width: 8),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 160),
                  child: Text(label,
                      overflow: TextOverflow.ellipsis,
                      style: hl(13.5, weight: FontWeight.w700, color: on ? Colors.white : (add ? kLeaf : kText))),
                ),
              ]),
            ),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 54,
        child: ListView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
          children: [
            for (final f in farms)
              _pill(
                on: f['id'] == selected,
                icon: const Icon(Icons.agriculture),
                label: '${f['name']}',
                onTap: () => onPick(f['id'] as int),
              ),
            _pill(on: false, add: true, icon: const Icon(Icons.add), label: t('addFarm'), onTap: onAdd),
          ],
        ),
      );
}

/// The farm's name and facts under the pills (the website's .hero).
class _FarmTitle extends StatelessWidget {
  const _FarmTitle({required this.farm, required this.onEdit});
  final Map<String, dynamic> farm;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    final facts = [
      if (farm['area_ha'] != null) '${fmtNum(farm['area_ha'], 2)} ${t('ha')}',
      if (farm['crop'] != null) cropName(farm['crop_names'], '${farm['crop_name'] ?? farm['crop']}'),
      if (farm['region'] != null) '${farm['region']}',
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 8, 6),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${farm['name']}', maxLines: 1, overflow: TextOverflow.ellipsis, style: hl(21)),
            if (facts.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(facts.join('  ·  '),
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13, color: kSubtle)),
              ),
          ]),
        ),
        OutlinedButton(
          style: OutlinedButton.styleFrom(
            minimumSize: const Size(44, 40),
            padding: const EdgeInsets.symmetric(horizontal: 10),
            side: const BorderSide(color: kOutlineSoft),
            backgroundColor: Colors.transparent,
          ),
          onPressed: onEdit,
          child: Tooltip(message: t('farmSettings'), child: const Icon(Icons.edit_outlined, size: 20)),
        ),
      ]),
    );
  }
}

/// The avatar with the farmer's initial; opens the account menu.
class _AccountButton extends StatelessWidget {
  const _AccountButton({required this.hasFarm, required this.onPick});
  final bool hasFarm;
  final ValueChanged<String> onPick;

  @override
  Widget build(BuildContext context) {
    final name = Api.I.userName;
    final initial = name.isNotEmpty ? name.characters.first.toUpperCase() : '·';
    PopupMenuItem<String> item(String v, IconData icon, String label, {Color color = kText}) => PopupMenuItem(
          value: v,
          child: Row(children: [
            Icon(icon, size: 20, color: color == kText ? kLeaf : color),
            const SizedBox(width: 12),
            Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w500)),
          ]),
        );
    return PopupMenuButton<String>(
      tooltip: name.isNotEmpty ? name : t('signOut'),
      position: PopupMenuPosition.under,
      onSelected: onPick,
      itemBuilder: (_) => [
        PopupMenuItem(
          enabled: false,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: const TextStyle(fontWeight: FontWeight.w600, color: kText)),
            Text(t('farmerRole').toUpperCase(),
                style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.6, color: kLeaf)),
          ]),
        ),
        const PopupMenuDivider(),
        if (hasFarm) item('settings', Icons.tune, t('farmSettings')),
        if (hasFarm) item('log', Icons.history, t('farmLog')),
        item('add', Icons.add_location_alt_outlined, t('addFarm')),
        const PopupMenuDivider(),
        item('logout', Icons.logout, t('signOut'), color: kDanger),
      ],
      child: Container(
        width: 36,
        height: 36,
        alignment: Alignment.center,
        decoration: const BoxDecoration(color: kPrimaryC, shape: BoxShape.circle),
        child: Text(initial, style: hl(14, weight: FontWeight.w700, color: Colors.white)),
      ),
    );
  }
}

/// The website's floating "AI Agronomist" button (.ai-fab): dark green, with a
/// light-blue ring, the assistant icon and its live dot.
class _AiButton extends StatelessWidget {
  const _AiButton({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Tooltip(
        message: t('aiTitle'),
        child: Material(
          color: kPrimary,
          elevation: 6,
          shadowColor: const Color(0x55012D1D),
          shape: const CircleBorder(side: BorderSide(color: Color(0x6669D4F4), width: 2)),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: const SizedBox(width: 58, height: 58, child: AiAvatar(size: 28)),
          ),
        ),
      );
}
