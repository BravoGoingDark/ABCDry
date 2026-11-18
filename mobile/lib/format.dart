import 'package:material_ui/material_ui.dart';
import 'package:intl/intl.dart';

import 'i18n.dart';

// The website's design tokens (templates/dashboard/farmer_home.html :root),
// so the app and the farmer web page look like one product.
const kPrimary = Color(0xFF012D1D); // --primary
const kPrimaryC = Color(0xFF1B4332); // --primary-c
const kSecondary = Color(0xFF00677D); // --secondary
const kSecondaryFixed = Color(0xFF69D4F4); // --secondary-fixed
const kLeaf = Color(0xFF2D6A4F); // --leaf
const kMint = Color(0xFFD8F3E3); // --mint
const kPage = Color(0xFFF6F7F5); // page background
const kSurface = Color(0xFFF9F9FF); // --surface
const kSurfaceLow = Color(0xFFF0F3FF); // --surface-low
const kSurfaceHigh = Color(0xFFE2E8F8); // --surface-high
const kCard = Colors.white; // --card
const kOutline = Color(0xFFC1C8C2); // --outline
const kOutlineSoft = Color(0xFFE3E8E4); // --outline-soft
const kText = Color(0xFF151C27); // --text
const kMuted = Color(0xFF414844); // --muted
const kSubtle = Color(0xFF717973); // --subtle
const kWater = Color(0xFF2563EB);
const kWaterDeep = Color(0xFF1D4ED8);
const kInfo = Color(0xFF00677D);
const kInfoBg = Color(0xFFE0F5FB);
const kWarn = Color(0xFF9A5B00); // --warn
const kWarnBg = Color(0xFFFFF4D6); // --warn-bg
const kDanger = Color(0xFFB3261E); // --danger
const kDangerBg = Color(0xFFFFE4E1); // --danger-bg
const kOk = Color(0xFF15803D); // --s1
const kOkBg = Color(0xFFDCFCE7); // --s1-bg

/// Titles and big numbers: Hanken Grotesk, extra bold, dark green (the website's h1/h2/.hl).
TextStyle hl(double size, {FontWeight weight = FontWeight.w800, Color color = kPrimary}) => TextStyle(
    fontFamily: 'HankenGrotesk', fontSize: size, fontWeight: weight, color: color, letterSpacing: -0.15, height: 1.2);

/// Small uppercase labels above a value (the website's .tk-head small / .tile .lbl).
const kCapsLabel = TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: kSubtle, letterSpacing: 0.5);

TextStyle _inter(double size, FontWeight w, [Color c = kText]) =>
    TextStyle(fontFamily: 'Inter', fontSize: size, fontWeight: w, color: c);

ThemeData appTheme() {
  const radius10 = BorderRadius.all(Radius.circular(10));
  final scheme = ColorScheme.fromSeed(
    seedColor: kLeaf,
    primary: kPrimary,
    onPrimary: Colors.white,
    secondary: kSecondary,
    secondaryContainer: kMint,
    onSecondaryContainer: kPrimary,
    surface: kCard,
    onSurface: kText,
    onSurfaceVariant: kMuted,
    surfaceContainerLowest: Colors.white,
    surfaceContainerLow: kSurface,
    surfaceContainer: kSurfaceLow,
    surfaceContainerHigh: kSurfaceLow,
    surfaceContainerHighest: kSurfaceHigh,
    outline: kOutline,
    outlineVariant: kOutlineSoft,
    error: kDanger,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    fontFamily: 'Inter',
    scaffoldBackgroundColor: kPage,
    textTheme: TextTheme(
      headlineSmall: hl(22),
      titleLarge: hl(19),
      titleMedium: hl(16, weight: FontWeight.w700),
      titleSmall: _inter(14, FontWeight.w600),
      bodyLarge: _inter(15, FontWeight.w400),
      bodyMedium: _inter(14, FontWeight.w400),
      bodySmall: _inter(12.5, FontWeight.w400, kSubtle),
      labelLarge: _inter(14, FontWeight.w600),
      labelMedium: _inter(12, FontWeight.w600, kMuted),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: kCard,
      foregroundColor: kPrimary,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
      titleTextStyle: hl(18),
      shape: const Border(bottom: BorderSide(color: kOutlineSoft)),
    ),
    cardTheme: const CardThemeData(
      color: kCard,
      elevation: 0,
      margin: EdgeInsets.symmetric(vertical: 6),
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(18)), side: BorderSide(color: kOutlineSoft)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: kPrimary,
        foregroundColor: Colors.white,
        minimumSize: const Size(0, 46),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        shape: const RoundedRectangleBorder(borderRadius: radius10),
        textStyle: _inter(14, FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        backgroundColor: kCard,
        foregroundColor: kPrimary,
        minimumSize: const Size(0, 46),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        side: const BorderSide(color: kOutline),
        shape: const RoundedRectangleBorder(borderRadius: radius10),
        textStyle: _inter(14, FontWeight.w600),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: kLeaf, textStyle: _inter(14, FontWeight.w600)),
    ),
    iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(foregroundColor: kMuted)),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      labelStyle: _inter(14, FontWeight.w500, kSubtle),
      hintStyle: _inter(14, FontWeight.w400, kSubtle),
      prefixIconColor: kSubtle,
      border: const OutlineInputBorder(borderRadius: radius10, borderSide: BorderSide(color: kOutline)),
      enabledBorder: const OutlineInputBorder(borderRadius: radius10, borderSide: BorderSide(color: kOutline)),
      focusedBorder:
          const OutlineInputBorder(borderRadius: radius10, borderSide: BorderSide(color: kSecondary, width: 2)),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        backgroundColor: kCard,
        foregroundColor: kMuted,
        selectedBackgroundColor: kPrimary,
        selectedForegroundColor: Colors.white,
        side: const BorderSide(color: kOutlineSoft),
        textStyle: _inter(13.5, FontWeight.w600),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: kCard,
      selectedColor: kPrimary,
      checkmarkColor: Colors.white,
      side: const BorderSide(color: kOutlineSoft),
      shape: const StadiumBorder(),
      labelStyle: WidgetStateTextStyle.resolveWith(
          (s) => _inter(13, FontWeight.w600, s.contains(WidgetState.selected) ? Colors.white : kMuted)),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Colors.transparent,
      elevation: 0,
      height: 68,
      indicatorColor: kMint,
      surfaceTintColor: Colors.transparent,
      labelTextStyle: WidgetStateTextStyle.resolveWith(
          (s) => _inter(11.5, FontWeight.w600, s.contains(WidgetState.selected) ? kPrimary : kSubtle)),
      iconTheme: WidgetStateProperty.resolveWith(
          (s) => IconThemeData(size: 24, color: s.contains(WidgetState.selected) ? kLeaf : kSubtle)),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: kCard,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(18))),
      titleTextStyle: hl(18, weight: FontWeight.w700),
    ),
    datePickerTheme: const DatePickerThemeData(backgroundColor: kCard, surfaceTintColor: Colors.transparent),
    popupMenuTheme: PopupMenuThemeData(
      color: kCard,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(14)), side: BorderSide(color: kOutlineSoft)),
      textStyle: _inter(14, FontWeight.w500),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: kPrimary,
      behavior: SnackBarBehavior.floating,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(12))),
      contentTextStyle: _inter(14, FontWeight.w500, Colors.white),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: kLeaf,
      titleTextStyle: _inter(14, FontWeight.w600),
      subtitleTextStyle: _inter(12.5, FontWeight.w400, kMuted),
    ),
    expansionTileTheme: const ExpansionTileThemeData(iconColor: kLeaf, collapsedIconColor: kSubtle),
    dividerTheme: const DividerThemeData(color: kOutlineSoft, space: 1),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: kLeaf),
  );
}

/// The APWRS logo as on the website header: round, on white, with a teal ring.
class BrandLogo extends StatelessWidget {
  const BrandLogo({super.key, this.size = 40});
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: const BoxDecoration(
          color: Colors.white,
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(color: Color(0x5900677D), spreadRadius: 4),
            BoxShadow(color: Colors.white, spreadRadius: 2),
          ],
        ),
        child: ClipOval(
          child: Padding(
            padding: EdgeInsets.all(size * 0.06),
            child: Image.asset('assets/img/apwrs-logo.png', fit: BoxFit.contain, filterQuality: FilterQuality.medium),
          ),
        ),
      );
}

/// EN · FR · ع, the website header's language switch.
class LangPill extends StatelessWidget {
  const LangPill({super.key, required this.onPick});
  final ValueChanged<String> onPick;
  static const _short = {'en': 'EN', 'fr': 'FR', 'ar': 'ع'};

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          color: kSurfaceLow,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: kOutlineSoft),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          for (final l in supportedLangs)
            Semantics(
              button: true,
              selected: l == appLang.value,
              label: langNames[l],
              child: InkWell(
                borderRadius: BorderRadius.circular(7),
                onTap: l == appLang.value ? null : () => onPick(l),
                child: Container(
                  constraints: const BoxConstraints(minWidth: 36, minHeight: 32),
                  alignment: Alignment.center,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  decoration: BoxDecoration(
                    color: l == appLang.value ? kPrimary : Colors.transparent,
                    borderRadius: BorderRadius.circular(7),
                  ),
                  child: Text(_short[l]!,
                      style: hl(12.5, weight: FontWeight.w700, color: l == appLang.value ? Colors.white : kMuted)),
                ),
              ),
            ),
        ]),
      );
}

DateTime _day(DateTime d) => DateTime(d.year, d.month, d.day);

DateTime parseDay(String iso) => DateTime.parse(iso.length > 10 ? iso.substring(0, 10) : iso);

String isoDay(DateTime d) => DateFormat('yyyy-MM-dd').format(d);

String todayIso() => isoDay(DateTime.now());

/// "17 Nov 2026", in the app language.
String fmtDate(String iso) => DateFormat.yMMMd(appLang.value).format(parseDay(iso));

/// "Mon 17", in the app language.
String shortDay(String iso) => DateFormat('EEE d', appLang.value).format(parseDay(iso));

int dayDiff(String iso) => _day(parseDay(iso)).difference(_day(DateTime.now())).inDays;

/// "Today", "Tomorrow", "In 3 days".
String relDay(String iso) {
  final n = dayDiff(iso);
  if (n == 0) return t('today');
  if (n == 1) return t('tomorrow');
  return t('inDays', {'n': n});
}

/// 12, 12.5 — no trailing zeros.
String fmtNum(Object? value, [int digits = 0]) {
  if (value == null) return '—';
  final v = (value as num).toDouble();
  final f = NumberFormat.decimalPattern(appLang.value == 'ar' ? 'en' : appLang.value)
    ..maximumFractionDigits = digits
    ..minimumFractionDigits = 0;
  return f.format(v);
}

Widget offlineBanner() => ValueListenableBuilder<bool>(
      valueListenable: offlineFlag,
      builder: (context, offline, _) => offline
          ? Container(
              width: double.infinity,
              color: const Color(0xFFFEF3C7),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
              child: Row(children: [
                const Icon(Icons.cloud_off, size: 18, color: Color(0xFF92400E)),
                const SizedBox(width: 8),
                Expanded(
                    child: Text(t('offline'),
                        style: const TextStyle(color: Color(0xFF92400E), fontWeight: FontWeight.w600, fontSize: 13))),
              ]),
            )
          : const SizedBox.shrink(),
    );

/// Set by main.dart to Api.I.offline (kept here so widgets need no Api import).
late ValueNotifier<bool> offlineFlag;

Widget errorView(Object error, VoidCallback retry) => Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.cloud_off, size: 40, color: kSubtle),
          const SizedBox(height: 12),
          Text('$error', textAlign: TextAlign.center),
          const SizedBox(height: 12),
          FilledButton.tonal(onPressed: retry, child: Text(t('retry'))),
        ]),
      ),
    );

void showMessage(BuildContext context, String text, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text), backgroundColor: error ? kDanger : kPrimary));
}
