// Talks to the APWRS server (the same farmer API as the web app).
//
// - Signs in with a token (POST /farmer/api/auth/login/), kept in the phone's
//   secure storage, and sends it as "Authorization: Token ...".
// - Sends the app language as Accept-Language: every text the server writes
//   (reminders, assistant answers, alerts, errors) comes back in it.
// - Every successful read is saved on the phone, so the app still opens with
//   the last data in the field without a connection. Changes always need the
//   network: they are never queued or faked.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'i18n.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.status});
  final String message;
  final int? status;
  @override
  String toString() => message;
}

class Api {
  Api._();
  static final Api I = Api._();

  /// Server address: build with --dart-define=API_URL=https://... to change it.
  static const String defaultBase = String.fromEnvironment('API_URL', defaultValue: 'https://abcdry-1.onrender.com');

  String base = defaultBase;
  String? token;
  String lang = 'en';
  http.Client client = http.Client();

  /// True while the last read came from the phone's saved copy.
  final ValueNotifier<bool> offline = ValueNotifier(false);

  /// Called when the server refuses the token (expired or revoked).
  VoidCallback? onSignedOut;

  static const _tokenKey = 'apwrs_token';
  static const _cachePrefix = 'cache:';
  final FlutterSecureStorage _secure = const FlutterSecureStorage();
  SharedPreferences? _prefs;

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    lang = _prefs!.getString('lang') ?? lang;
    // Always use the build-configured server. A saved server can make the
    // phone authenticate against a different database from the website.
    base = defaultBase;
    await _prefs!.remove('server');
    try {
      token = await _secure.read(key: _tokenKey);
    } catch (_) {
      token = null;
    }
  }

  SharedPreferences? get prefs => _prefs;

  /// The signed-in farmer's name, for the header avatar.
  String get userName => _prefs?.getString('user_name') ?? '';

  Future<void> setLang(String value) async {
    lang = value;
    await _prefs?.setString('lang', value);
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Accept-Language': lang,
        if (token != null) 'Authorization': 'Token $token',
      };

  Uri _uri(String path) => Uri.parse('$base$path');

  dynamic _decode(http.Response r) {
    dynamic data;
    try {
      data = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      data = null;
    }
    if (r.statusCode == 401 && token != null) {
      signOutLocally();
      onSignedOut?.call();
    }
    if (r.statusCode >= 400) {
      final msg = data is Map && data['error'] != null ? '${data['error']}' : '${tr(lang, 'error')} ${r.statusCode}';
      throw ApiException(msg, status: r.statusCode);
    }
    return data;
  }

  /// GET with the saved copy as fallback when there is no connection.
  Future<dynamic> get(String path) async {
    final key = '$_cachePrefix$lang:$path';
    try {
      final r = await client.get(_uri(path), headers: _headers).timeout(const Duration(seconds: 30));
      final data = _decode(r);
      await _prefs?.setString(key, utf8.decode(r.bodyBytes));
      offline.value = false;
      return data;
    } on ApiException {
      rethrow;
    } catch (_) {
      final saved = _prefs?.getString(key);
      offline.value = true;
      if (saved != null) return jsonDecode(saved);
      throw ApiException(tr(lang, 'noConnection'));
    }
  }

  Future<dynamic> send(String method, String path, [Object? body]) async {
    final request = http.Request(method, _uri(path))..headers.addAll(_headers);
    if (body != null) request.body = jsonEncode(body);
    try {
      final streamed = await client.send(request).timeout(const Duration(seconds: 45));
      final r = await http.Response.fromStream(streamed);
      offline.value = false;
      return _decode(r);
    } on ApiException {
      rethrow;
    } catch (_) {
      offline.value = true;
      throw ApiException(tr(lang, 'noConnection'));
    }
  }

  Future<dynamic> post(String path, [Object? body]) => send('POST', path, body);
  Future<dynamic> patch(String path, Object body) => send('PATCH', path, body);
  Future<dynamic> delete(String path) => send('DELETE', path);

  Future<Map<String, dynamic>> login(String username, String password) async {
    final data = await post('/farmer/api/auth/login/', {'username': username, 'password': password});
    token = data['token'] as String;
    await _secure.write(key: _tokenKey, value: token);
    final user = Map<String, dynamic>.from(data['user'] as Map);
    await _prefs?.setString('user_name', '${user['name'] ?? user['username'] ?? ''}');
    return user;
  }

  Future<void> logout() async {
    try {
      await post('/farmer/api/auth/logout/');
    } catch (_) {
      // offline: the token is still forgotten on this phone
    }
    await signOutLocally();
  }

  /// Forget the token and every saved farm answer on this phone.
  Future<void> signOutLocally() async {
    token = null;
    try {
      await _secure.delete(key: _tokenKey);
    } catch (_) {}
    final prefs = _prefs;
    await prefs?.remove('user_name');
    if (prefs != null) {
      for (final k in prefs.getKeys().where((k) => k.startsWith(_cachePrefix)).toList()) {
        await prefs.remove(k);
      }
    }
  }
}
