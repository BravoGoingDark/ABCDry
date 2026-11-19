import 'dart:convert';
import 'dart:math' as math;

import 'package:apwrs_farmer/api.dart';
import 'package:apwrs_farmer/auth_widgets.dart' show AuthField;
import 'package:apwrs_farmer/format.dart';
import 'package:apwrs_farmer/geo.dart';
import 'package:apwrs_farmer/i18n.dart';
import 'package:apwrs_farmer/screens/boundary_screen.dart';
import 'package:apwrs_farmer/screens/crop_tab.dart';
import 'package:apwrs_farmer/screens/farm_settings_screen.dart';
import 'package:apwrs_farmer/screens/login_screen.dart';
import 'package:apwrs_farmer/screens/signup_screen.dart';
import 'package:apwrs_farmer/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:cupertino_ui/cupertino_ui.dart' show GlobalCupertinoLocalizations;
import 'package:flutter_localizations/flutter_localizations.dart' show GlobalWidgetsLocalizations;
import 'package:flutter_map/flutter_map.dart' show FlutterMap;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUpAll(() async {
    await initializeDateFormatting();
    offlineFlag = Api.I.offline;
  });

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    FlutterSecureStorage.setMockInitialValues({});
    await Api.I.load();
    Api.I.base = 'https://test.example';
    Api.I.lang = 'en';
    Api.I.token = null;
    appLang.value = 'en';
  });

  test('every screen text exists in English, French and Arabic', () {
    final en = keysFor('en');
    expect(keysFor('fr'), en);
    expect(keysFor('ar'), en);
    expect(tr('ar', 'inDays', {'n': 3}), 'بعد 3 أيام');
  });

  test('sign in keeps the token and sends it with the language', () async {
    final seen = <http.BaseRequest>[];
    Api.I.client = MockClient((req) async {
      seen.add(req);
      if (req.url.path == '/farmer/api/auth/login/') {
        return http.Response(jsonEncode({'token': 'abc', 'user': {'username': 'mona'}}), 200);
      }
      return http.Response(jsonEncode({'farms': []}), 200);
    });
    await Api.I.login('mona', 'pw');
    Api.I.lang = 'ar';
    await Api.I.get('/farmer/api/farms/');
    expect(seen.last.headers['Authorization'], 'Token abc');
    expect(seen.last.headers['Accept-Language'], 'ar');
  });

  test('reads are saved for the field and used offline', () async {
    var online = true;
    Api.I.client = MockClient((req) async {
      if (!online) throw http.ClientException('no network');
      return http.Response(jsonEncode({'tasks': ['water 23 mm']}), 200);
    });
    final first = await Api.I.get('/farmer/api/farms/1/tasks/');
    expect(Api.I.offline.value, isFalse);
    online = false;
    final again = await Api.I.get('/farmer/api/farms/1/tasks/');
    expect(again, first);
    expect(Api.I.offline.value, isTrue);
    await expectLater(Api.I.get('/farmer/api/never-read/'), throwsA(isA<ApiException>()));
  });

  test('changes are never faked offline', () async {
    Api.I.client = MockClient((req) async => throw http.ClientException('no network'));
    await expectLater(
      Api.I.post('/farmer/api/farms/1/activities/', {'kind': 'irrigation'}),
      throwsA(predicate((e) => e is ApiException && e.message == tr('en', 'noConnection'))),
    );
  });

  test('a refused token signs the phone out and forgets saved data', () async {
    var signedOut = false;
    Api.I.onSignedOut = () => signedOut = true;
    Api.I.client = MockClient((req) async => http.Response(jsonEncode({'farms': []}), 200));
    Api.I.token = 'old';
    await Api.I.get('/farmer/api/farms/');
    Api.I.client = MockClient((req) async => http.Response(jsonEncode({'error': 'Invalid or expired login.'}), 401));
    await expectLater(Api.I.get('/farmer/api/farms/'), throwsA(isA<ApiException>()));
    await Future<void>.delayed(Duration.zero);
    expect(signedOut, isTrue);
    expect(Api.I.token, isNull);
    expect(Api.I.prefs!.getKeys().where((k) => k.startsWith('cache:')), isEmpty);
  });

  Widget host(Widget child, {String lang = 'en'}) => MaterialApp(
        locale: Locale(lang),
        supportedLocales: const [Locale('en'), Locale('fr'), Locale('ar')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: Scaffold(body: SingleChildScrollView(child: child)),
      );

  final question = {
    'key': 'irr-missed:2026-11-06',
    'kind': 'irrigation',
    'state': 'ask',
    'date': '2026-11-06',
    'text': {
      'title': 'Did you water since 6 Nov 2026?',
      'why': ['Watering was due on 6 Nov 2026.'],
      'how': ['If not, water today: 23 mm.'],
    },
    'answer': {'type': 'irrigation', 'min_date': '2026-11-06', 'dose_mm': 23},
    'products': [],
  };

  testWidgets('a question shows what, why, how and the answers', (tester) async {
    String? action;
    await tester.pumpWidget(host(TaskCard(task: question, onAction: (a) => action = a)));
    expect(find.text('Did you water since 6 Nov 2026?'), findsOneWidget);
    expect(find.text('Watering was due on 6 Nov 2026.'), findsOneWidget);
    expect(find.text('If not, water today: 23 mm.'), findsOneWidget);
    await tester.tap(find.text('No, not yet'));
    expect(action, 'skip');
    await tester.tap(find.text('Yes, I watered'));
    expect(action, 'form');
  });

  testWidgets('the card is in Arabic and right to left', (tester) async {
    appLang.value = 'ar';
    await tester.pumpWidget(host(TaskCard(task: question, onAction: (_) {}), lang: 'ar'));
    expect(find.text('نعم، سقيت'), findsOneWidget);
    expect(Directionality.of(tester.element(find.byType(TaskCard))), TextDirection.rtl);
  });

  final plan = {
    'crop': 'wheat',
    'names': {'en': 'durum wheat', 'fr': 'blé dur', 'ar': 'القمح الصلب'},
    'area_ha': 2.0,
    'calendar': {
      'sowing_date': '2099-11-01',
      'events': [
        {'date': '2000-01-01', 'kind': 'stage', 'title': 'Long ago', 'detail': ''},
        {'date': '2099-11-01', 'kind': 'stage', 'title': 'Sowing / planting', 'detail': ''},
        {'date': '2099-12-21', 'kind': 'fertilizer', 'title': 'Start of tillering', 'detail': 'Ammonium nitrate 33.5%: 100-150 kg/ha'},
      ],
    },
    'fertilizer': {
      'totals': {'N': [80, 120], 'P2O5': [45, 70]},
      'note': 'K is rarely needed.',
      'schedule': [
        {
          'offset_days': 0,
          'stage': 'Sowing (incorporated)',
          'product': 'DAP 18-46-0',
          'rate': '100-150 kg/ha',
          'details': {
            'products': [],
            'farm': {'area_ha': 2.0, 'kg': '200-300', 'bags': '4-6', 'bag_kg': 50},
          },
        },
      ],
    },
    'fertilizer_notice': 'Check the label.',
    'protection': [
      {
        'name': 'Septoria leaf blotch',
        'months': [2, 3, 4],
        'watch': 'Brown blotches on lower leaves.',
        'prevent': 'Rotation.',
        'control': 'Triazole fungicide at flag leaf.',
        'products': [
          {'kind': 'chemical', 'group': 'FRAC 3', 'name': 'Tebuconazole', 'rate': '1 L/ha', 'notes': '', 'farm': '2 L'},
        ],
      },
    ],
    'protection_notice': 'Follow the label.',
  };

  testWidgets('the crop plan shows the calendar, fertiliser for the farm and pests', (tester) async {
    await tester.pumpWidget(host(CropPlanView(plan: plan)));
    expect(find.text('Long ago'), findsNothing); // older than a month: hidden
    expect(find.text('Sowing / planting'), findsOneWidget);
    expect(find.text('Start of tillering'), findsOneWidget);
    expect(find.text('Your farm (2 ha): 200-300 kg = 4-6 bags of 50 kg'), findsOneWidget);
    expect(find.text('N 80–120 kg/ha'), findsOneWidget);
    expect(find.text('Septoria leaf blotch'), findsOneWidget);
    await tester.tap(find.text('Septoria leaf blotch'));
    await tester.pumpAndSettle();
    expect(find.text('Triazole fungicide at flag leaf.'), findsOneWidget);
    expect(find.textContaining('Tebuconazole (FRAC 3)'), findsOneWidget);
    expect(find.textContaining('→ 2 L'), findsOneWidget);
  });

  testWidgets('farm settings send the crop, sowing date and irrigation', (tester) async {
    // A phone-tall screen, so the whole form is built.
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    final sent = <Map>[];
    Api.I.client = MockClient((req) async {
      if (req.url.path == '/farmer/api/crops/') {
        return http.Response.bytes(
            utf8.encode(jsonEncode({
              'crops': [
                {'key': 'wheat', 'names': {'en': 'durum wheat', 'fr': 'blé dur', 'ar': 'القمح الصلب'}, 'perennial': false, 'planting_months': [11, 12]},
                {'key': 'olive', 'names': {'en': 'olive', 'fr': 'olivier', 'ar': 'الزيتون'}, 'perennial': true, 'planting_months': [2, 3]},
              ]
            })),
            200);
      }
      sent.add({'method': req.method, 'path': req.url.path, 'body': jsonDecode(req.body)});
      return http.Response(jsonEncode({'farm': {}}), 200);
    });
    final farm = {
      'id': 7,
      'name': 'North field',
      'crop': 'wheat',
      'sowing_date': '2026-11-01',
      'irrigated': false,
      'irrigation_method': null,
      'irrigation_flow_m3h': null,
      'water_supply_mm': null,
    };
    await tester.pumpWidget(MaterialApp(home: FarmSettingsScreen(farm: farm)));
    await tester.pumpAndSettle();
    expect(find.text('durum wheat'), findsOneWidget);
    expect(find.text('Usual sowing months: November, December'), findsOneWidget);

    await tester.tap(find.text('Irrigated'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Drip'));
    await tester.ensureVisible(find.byKey(const ValueKey('flow-field')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('flow-field')), '12,5');
    await tester.ensureVisible(find.text('Save'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(sent.single['method'], 'PATCH');
    expect(sent.single['path'], '/farmer/api/farms/7/');
    expect(sent.single['body'], {
      'name': 'North field',
      'crop': 'wheat',
      'sowing_date': '2026-11-01',
      'irrigated': true,
      'irrigation_method': 'drip',
      'irrigation_flow_m3h': 12.5,
      'water_supply_mm': null,
    });
  });

  testWidgets('a crop picked from the ranking starts without the old sowing date', (tester) async {
    Api.I.client = MockClient((req) async => http.Response(jsonEncode({'crops': []}), 200));
    await tester.pumpWidget(MaterialApp(
        home: FarmSettingsScreen(
            farm: const {'id': 7, 'name': 'A', 'crop': 'wheat', 'sowing_date': '2026-11-01', 'irrigated': false},
            initialCrop: 'olive')));
    await tester.pumpAndSettle();
    expect(find.text('Not sown yet'), findsOneWidget);
  });

  testWidgets('a farm without a name is not sent', (tester) async {
    var calls = 0;
    Api.I.client = MockClient((req) async {
      if (req.url.path != '/farmer/api/crops/') calls++;
      return http.Response(jsonEncode({'crops': []}), 200);
    });
    await tester.pumpWidget(MaterialApp(home: FarmSettingsScreen(farm: const {'id': 7, 'name': 'A', 'irrigated': false})));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, '  ');
    await tester.ensureVisible(find.text('Save'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(calls, 0);
    expect(find.text('The farm needs a name.'), findsOneWidget);
  });

  test('the farm area and limits match the server', () {
    // ~100 m x 100 m near Meknes: about one hectare
    const lat = 33.9, lon = -5.55;
    const dLat = 100 / 111195.0;
    final dLon = 100 / (111195.0 * math.cos(lat * math.pi / 180));
    final square = [
      const LatLng(lat, lon),
      LatLng(lat, lon + dLon),
      LatLng(lat + dLat, lon + dLon),
      LatLng(lat + dLat, lon),
    ];
    expect(areaHa(square), closeTo(1.0, 0.01));
    expect(areaHa(square.reversed.toList()), closeTo(1.0, 0.01));
    expect(boundaryProblem(square), isNull);
    expect(boundaryProblem(square.take(2).toList()), 'needThreeCorners');
    final tiny = [for (final p in square) LatLng(lat + (p.latitude - lat) / 20, lon + (p.longitude - lon) / 20)];
    expect(boundaryProblem(tiny), 'parcelTooSmall');

    final json = toGeoJson(square);
    final ring = (json['coordinates'] as List).first as List;
    expect(json['type'], 'Polygon');
    expect(ring.length, 5);
    expect(ring.first, ring.last);
    expect(ring.first, [lon, lat]); // GeoJSON is [lon, lat]
    final back = fromGeoJson(json);
    expect(back.length, 4);
    expect(back[2].latitude, closeTo(square[2].latitude, 1e-7));
    expect(fromGeoJson(null), isEmpty);
  });

  /// Opens [screen] from a first page; the returned function gives what it popped.
  Future<Future<Map<String, dynamic>?> Function()> openFrom(WidgetTester tester, Widget screen) async {
    Map<String, dynamic>? popped;
    var done = false;
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => TextButton(
          onPressed: () async {
            popped = await Navigator.push<Map<String, dynamic>>(context, MaterialPageRoute(builder: (_) => screen));
            done = true;
          },
          child: const Text('open'),
        ),
      ),
    ));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    return () async {
      expect(done, isTrue, reason: 'the map screen was not closed');
      return popped;
    };
  }

  Future<void> tapMap(WidgetTester tester, Offset fromCentre) async {
    await tester.tapAt(tester.getCenter(find.byType(FlutterMap)) + fromCentre);
    await tester.pump(const Duration(milliseconds: 600)); // past the double-tap wait
  }

  void tallPhone(WidgetTester tester) {
    tester.view.physicalSize = const Size(800, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
  }

  testWidgets('a new farm is marked on the map and sent with its name', (tester) async {
    tallPhone(tester);
    final sent = <Map<String, dynamic>>[];
    Api.I.client = MockClient((req) async {
      sent.add({'method': req.method, 'path': req.url.path, 'body': jsonDecode(req.body)});
      return http.Response(jsonEncode({'farm': {'id': 9, 'name': 'Olive grove', 'area_ha': 1.2}}), 201);
    });
    const here = LatLng(33.9, -5.55);
    final result = await openFrom(
        tester, BoundaryScreen(showTiles: false, locate: () async => (point: here, accuracy: 6.0)));
    expect(find.text('Mark your farm'), findsOneWidget);
    expect(find.text('0 corners · 0 ha'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Save')).onPressed, isNull);

    // one corner where the farmer stands, two tapped on the map
    await tester.tap(find.text('Corner where I stand'));
    await tester.pumpAndSettle();
    expect(find.text('Corner added (accurate to 6 m).'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5)); // the message leaves the Save button free
    await tester.pumpAndSettle();
    await tapMap(tester, const Offset(100, 0));
    await tapMap(tester, const Offset(100, -100));
    // a fourth corner, then tapped again: removed
    await tapMap(tester, const Offset(0, -100));
    expect(find.textContaining('4 corners'), findsOneWidget);
    await tapMap(tester, const Offset(0, -100));
    expect(find.textContaining('3 corners'), findsOneWidget);

    // no name: refused here, nothing sent
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();
    expect(find.text('The farm needs a name.'), findsOneWidget);
    expect(sent, isEmpty);

    await tester.enterText(find.byKey(const ValueKey('farm-name')), ' Olive grove ');
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();

    expect(sent.single['method'], 'POST');
    expect(sent.single['path'], '/farmer/api/farms/');
    final body = sent.single['body'] as Map;
    expect(body['name'], 'Olive grove');
    final ring = (body['boundary']['coordinates'] as List).first as List;
    expect(ring.length, 4);
    expect(ring.first, [here.longitude, here.latitude]);
    expect(ring.last, ring.first);
    expect((await result())?['id'], 9);
  });

  testWidgets('redrawing a border sends only the new border', (tester) async {
    tallPhone(tester);
    final sent = <Map<String, dynamic>>[];
    Api.I.client = MockClient((req) async {
      sent.add({'method': req.method, 'path': req.url.path, 'body': jsonDecode(req.body)});
      return http.Response(jsonEncode({'farm': {'id': 7, 'area_ha': 0.6}}), 200);
    });
    final boundary = {
      'type': 'Polygon',
      'coordinates': [
        [
          [-5.55, 33.9],
          [-5.549, 33.9],
          [-5.549, 33.901],
          [-5.55, 33.901],
          [-5.55, 33.9],
        ],
      ],
    };
    var gpsAsked = false;
    final result = await openFrom(
        tester,
        BoundaryScreen(
          farm: {'id': 7, 'name': 'North field', 'boundary': boundary},
          showTiles: false,
          locate: () async {
            gpsAsked = true;
            throw GpsException('gpsOff');
          },
        ));
    expect(gpsAsked, isFalse); // an existing farm opens on its border, not on the phone
    expect(find.text('Redraw the border'), findsOneWidget);
    expect(find.textContaining('4 corners'), findsOneWidget);
    expect(find.byKey(const ValueKey('farm-name')), findsNothing);

    await tester.tap(find.byTooltip('Undo'));
    await tester.pump();
    expect(find.textContaining('3 corners'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();

    expect(sent.single['method'], 'PATCH');
    expect(sent.single['path'], '/farmer/api/farms/7/');
    expect((sent.single['body'] as Map).keys, ['boundary']);
    expect(((sent.single['body']['boundary']['coordinates'] as List).first as List).length, 4);
    expect((await result())?['area_ha'], 0.6);
  });

  testWidgets('without GPS the farmer is told how to fix it', (tester) async {
    tallPhone(tester);
    await tester.pumpWidget(
        MaterialApp(home: BoundaryScreen(showTiles: false, locate: () async => throw GpsException('gpsDenied'))));
    await tester.pumpAndSettle();
    // the automatic look-up on opening stays quiet
    expect(find.byType(SnackBar), findsNothing);
    await tester.tap(find.text('Corner where I stand'));
    await tester.pumpAndSettle();
    expect(find.text('The app is not allowed to use your location: allow it in the phone settings.'), findsOneWidget);
    expect(find.textContaining('0 corners'), findsOneWidget);
  });

  Future<void> fillSignup(WidgetTester tester, {String confirm = 'olive-123'}) async {
    Future<void> type(String label, String text) =>
        tester.enterText(authField(label), text);
    await type('Username', 'nadia');
    await type('Phone number', '+216 20 000 000');
    await type('Password', 'olive-123');
    await type('Confirm password', confirm);
    await tester.ensureVisible(find.text('Create account'));
    await tester.tap(find.text('Create account'));
    await tester.pumpAndSettle();
  }

  testWidgets('sign-up sends the website form, signs in and welcomes the farmer', (tester) async {
    tallPhone(tester);
    final sent = <Map<String, dynamic>>[];
    Api.I.client = MockClient((req) async {
      sent.add({'path': req.url.path, 'body': jsonDecode(req.body)});
      return http.Response(
          jsonEncode({'token': 'new-token', 'user': {'username': 'nadia', 'name': 'nadia', 'role': 'farmer'}}), 201);
    });
    bool? created;
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => TextButton(
          onPressed: () async =>
              created = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => const SignupScreen())),
          child: const Text('open'),
        ),
      ),
    ));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('Join APWRS as a farmer'), findsOneWidget);

    await fillSignup(tester);
    expect(sent.single['path'], '/farmer/api/auth/signup/');
    expect(sent.single['body'], {
      'username': 'nadia',
      'email': '',
      'phone': '+216 20 000 000',
      'password1': 'olive-123',
      'password2': 'olive-123',
    });
    expect(Api.I.token, 'new-token');
    expect(find.text('Welcome, nadia!'), findsOneWidget);
    await tester.tap(find.text('Start'));
    await tester.pumpAndSettle();
    expect(created, isTrue);
  });

  testWidgets('a refused sign-up shows why, under the field and in a popup', (tester) async {
    tallPhone(tester);
    Api.I.client = MockClient((req) async => http.Response.bytes(
        utf8.encode(jsonEncode({
          'error': 'This username is already taken.',
          'errors': {'username': 'This username is already taken.'},
        })),
        400));
    await tester.pumpWidget(const MaterialApp(home: SignupScreen()));
    await fillSignup(tester);
    expect(find.text('Could not create the account'), findsOneWidget);
    expect(find.text('This username is already taken.'), findsNWidgets(2)); // popup + under the field
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(find.text('This username is already taken.'), findsOneWidget);
    expect(Api.I.token, isNull);
  });

  testWidgets('passwords that differ never reach the server', (tester) async {
    tallPhone(tester);
    var calls = 0;
    Api.I.client = MockClient((req) async {
      calls++;
      return http.Response('{}', 201);
    });
    await tester.pumpWidget(const MaterialApp(home: SignupScreen()));
    await fillSignup(tester, confirm: 'olive-999');
    expect(calls, 0);
    expect(find.text('The two passwords do not match.'), findsNWidgets(2));
  });

  testWidgets('a refused sign-in is explained in a popup', (tester) async {
    tallPhone(tester);
    Api.I.client = MockClient((req) async =>
        http.Response(jsonEncode({'error': 'Wrong username or password.'}), 401));
    var signedIn = false;
    await tester.pumpWidget(MaterialApp(home: LoginScreen(onSignedIn: () => signedIn = true)));
    expect(find.text('Server'), findsNothing);
    expect(find.text('Sign up'), findsOneWidget);
    await tester.enterText(authField('Username'), 'mona');
    await tester.enterText(authField('Password'), 'nope');
    await tester.tap(find.text('Sign in'));
    await tester.pumpAndSettle();
    expect(find.text('Could not sign in'), findsOneWidget);
    expect(find.text('Wrong username or password.'), findsOneWidget);
    expect(signedIn, isFalse);
  });
}

/// The text box of the sign-in / sign-up field labelled [label] (the label
/// sits above the box, as on the website).
Finder authField(String label) =>
    find.descendant(of: find.widgetWithText(AuthField, label), matching: find.byType(TextField));
