# APWRS Farmer (Flutter)

The phone app for farmer accounts. It uses the same farmer API as the web
farmer area (`/farmer/api/...` in `dashboard/urls.py`), signed in with a token.

## What it does

| Screen | File | Server endpoint |
|---|---|---|
| Sign in | `lib/screens/login_screen.dart` | `POST auth/login/` |
| Add a farm / redraw its border on a satellite map (tap corners, or stand on them and use GPS) | `lib/screens/boundary_screen.dart` | `POST farms/`, `PATCH farms/<id>/` |
| Today: reminders and questions | `lib/screens/today_tab.dart` | `farms/<id>/tasks/` |
| Water: next watering, soil water, pump time | `lib/screens/water_tab.dart` | `farms/<id>/irrigation/` |
| Crop: calendar, fertiliser, pests, best crops here | `lib/screens/crop_tab.dart` | `farms/<id>/advice/`, `crop-plan/` |
| Weather and field alerts | `lib/screens/weather_tab.dart` | `farms/<id>/weather/` |
| Assistant | `lib/screens/chat_tab.dart` | `/assistant/chat/` |
| Farm log (add, correct, delete) | `lib/screens/log_screen.dart` | `farms/<id>/activities/` |
| Farm settings (crop, sowing, irrigation, border, delete) | `lib/screens/farm_settings_screen.dart` | `PATCH/DELETE farms/<id>/` |

- **Languages:** English, French and Arabic (right to left). The app's own
  texts are in `lib/i18n.dart`; everything the server writes comes back in the
  app language because it is sent as `Accept-Language`.
- **Offline:** every read is saved on the phone and shown when there is no
  connection. Changes always need the network and are never faked.
- **Map tiles** come through the server's tile proxy
  (`/api/tiles/{z}/{x}/{y}.png?layer=satellite|map`), like the website.
- **Farm geometry** (`lib/geo.dart`) uses the same area formula and limits as
  `dashboard/services/farmer_service.py`, so a shape the server would refuse is
  flagged before it is sent.

## Running it

The Flutter SDK is in `C:/Users/Taha/flutter/bin` (not on PATH):

```sh
export PATH="/c/Users/Taha/flutter/bin:$PATH"
flutter pub get
flutter analyze
flutter test
flutter run --dart-define=API_URL=https://your-server.example
```

`API_URL` defaults to the hosted server; it can also be changed on the
sign-in screen. The app uses the `material_ui` / `cupertino_ui` packages,
not `package:flutter/material.dart`.

Location permission (for marking corners) is declared in
`android/app/src/main/AndroidManifest.xml` and `ios/Runner/Info.plist`.
