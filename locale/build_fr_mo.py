"""Build locale/fr/LC_MESSAGES/django.mo from inline strings (no system gettext). Run: python locale/build_fr_mo.py"""
from __future__ import annotations

import pathlib

import polib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PO_PATH = ROOT / "locale" / "fr" / "LC_MESSAGES" / "django.po"
MO_PATH = ROOT / "locale" / "fr" / "LC_MESSAGES" / "django.mo"

# msgid (English) -> msgstr (French)
PAIRS: list[tuple[str, str]] = [
    ("High risk", "Risque élevé"),
    ("Moderate risk", "Risque modéré"),
    ("Low risk", "Risque faible"),
    (
        "Current soil salinity levels in sector 4 are incompatible with durum wheat under drip irrigation. "
        "Consider switching to highly salt-tolerant crops or scheduling intensive leaching protocols before sowing.",
        "Les niveaux actuels de salinité du sol dans le secteur 4 sont incompatibles avec le blé dur sous "
        "irrigation goutte-à-goutte. Envisagez des cultures très tolérantes au sel ou des protocoles de "
        "lessivage intensifs avant le semis.",
    ),
    (
        "The crop is generally suitable. Monitor soil moisture and optimize water application.",
        "La culture est globalement adaptée. Surveillez l'humidité du sol et optimisez l'apport en eau.",
    ),
    (
        "Current indicators are favorable. Continue weekly monitoring.",
        "Les indicateurs actuels sont favorables. Poursuivez un suivi hebdomadaire.",
    ),
    ("Ichkeul National Park, Tunisia", "Parc national d'Ichkeul, Tunisie"),
    ("Rabat area, Morocco", "Région de Rabat, Maroc"),
    ("Algiers area, Algeria", "Région d'Alger, Algérie"),
    ("Lake Ichkeul", "Lac Ichkeul"),
    ("Lake Ghezala", "Lac de Ghezala"),
    ("Lake of Bizerte", "Lac de Bizerte"),
    ("Dayet Aoua", "Dayet Aoua"),
    ("Lake Afennourir", "Lac Afennourir"),
    ("Bin el Ouidane", "Bin el Ouidane"),
    ("Lake Oubeira", "Lac Oubeira"),
    ("Lake Fetzara", "Lac Fetzara"),
    ("Lake Mellah", "Lac Mellah"),
    ("Map centered on __PLACE__.", "Carte centrée sur __PLACE__."),
    ("All drawings have been removed.", "Tous les dessins ont été supprimés."),
    (
        "Selection mode: click a drawn area to see its details.",
        "Mode sélection : cliquez sur une surface dessinée pour voir ses informations.",
    ),
    ("Draw mode: trace a polygon to measure the area.", "Mode dessin : tracez un polygone pour mesurer la surface."),
    (
        "Ruler mode: click two points on the map to measure distance.",
        "Mode règle : cliquez deux points sur la carte pour mesurer la distance.",
    ),
    (
        "Ping mode: click a point for exact live metrics.",
        "Mode ping : cliquez un point pour obtenir les métriques en direct exactes.",
    ),
    ("Ruler measurement cleared.", "Mesure de la règle supprimée."),
    (
        "Ping saved, but live metrics are unavailable for now.",
        "Ping enregistré, mais les métriques en direct sont momentanément indisponibles.",
    ),
    ("First point recorded. Click the second point.", "Premier point enregistré. Cliquez le deuxième point."),
    ("Distance: __M__ m (__KM__ km).", "Distance : __M__ m (__KM__ km)."),
    (
        "Area: __M2__ m² (__HA__ ha, __KM2__ km²) | Perimeter: __PM__ m | Center: __LAT__, __LNG__",
        "Surface : __M2__ m² (__HA__ ha, __KM2__ km²) | Périmètre : __PM__ m | Centre : __LAT__, __LNG__",
    ),
    (
        "Ping: __LAT__, __LNG__ | Wind: __WS__ km/h | Temp: __T__°C | Humidity: __H__% | Rain: __R__ mm",
        "Ping : __LAT__, __LNG__ | Vent : __WS__ km/h | Temp : __T__°C | Humidité : __H__% | Pluie : __R__ mm",
    ),
    # Template strings
    ("APWRS — Adaptive Planting Window Recommendation System", "APWRS — outil d'évaluation du risque de sécheresse"),
    ("Drought risk assessment tool", "Outil d'évaluation du risque de sécheresse"),
    ("Home", "Accueil"),
    ("Maps", "Cartes"),
    ("Reports", "Rapports"),
    ("Download", "Télécharger"),
    ("Help", "Aide"),
    ("Search…", "Rechercher…"),
    ("Run simulation", "Lancer la simulation"),
    ("Account", "Compte"),
    ("Water heat map", "Carte de chaleur de l'eau"),
    ("Optimal", "Optimal"),
    ("Marginal", "Marginal"),
    ("Critical risk", "Risque critique"),
    ("Measure", "Mesure"),
    ("Choose a tool to begin.", "Choisissez un outil pour commencer."),
    ("Clear drawings", "Effacer les dessins"),
    ("Clear ruler", "Effacer la règle"),
    ("Agricultural inputs simulator", "Simulateur d'intrants agricoles"),
    ("Crop type", "Type de culture"),
    ("Irrigation method", "Méthode d'irrigation"),
    ("Analyze risk", "Analyser le risque"),
    ("Wind dynamics", "Dynamique du vent"),
    ("Gusts up to", "Rafales jusqu'à"),
    ("Precipitation", "Précipitations"),
    ("% vs avg", "% vs moy."),
    ("Soil health", "Santé du sol"),
    ("pH level", "Niveau pH"),
    ("NPK fertility", "Fertilité NPK"),
    ("Microclimate", "Micro-climat"),
    ("Temperature", "Température"),
    ("Humidity", "Humidité"),
    ("Sponsors and partners", "Sponsors et partenaires"),
    ("Ministry of Agriculture", "Ministère de l'Agriculture"),
    ("LIVE", "EN DIRECT"),
    ("MONTHLY", "MENSUEL"),
    ("ZONE A", "ZONE A"),
    ("OPTIMAL", "OPTIMAL"),
    ("Drawing tool", "Outil de dessin"),
    ("Measure area", "Mesurer la surface"),
    ("Select region", "Sélectionner une région"),
    ("Ping point", "Point ping"),
]


def main() -> None:
    PO_PATH.parent.mkdir(parents=True, exist_ok=True)
    po = polib.POFile()
    po.metadata = {
        "Project-Id-Version": "APWRS",
        "Language": "fr",
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
    }
    for msgid, msgstr in PAIRS:
        po.append(polib.POEntry(msgid=msgid, msgstr=msgstr))
    po.save(str(PO_PATH))
    po.save_as_mofile(str(MO_PATH))
    print("Wrote", PO_PATH, "and", MO_PATH)


if __name__ == "__main__":
    main()
