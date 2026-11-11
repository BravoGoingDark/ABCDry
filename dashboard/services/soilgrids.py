"""ISRIC SoilGrids 2.0 point queries (250 m, global, no API key).

Docs: https://rest.isric.org/soilgrids/v2.0/docs  (fair use: 5 requests/min)
"""
import requests

URL = 'https://rest.isric.org/soilgrids/v2.0/properties/query'
PROPERTIES = ('sand', 'silt', 'clay', 'phh2o', 'soc')
DEPTHS = (('0-5cm', 5), ('5-15cm', 10), ('15-30cm', 15))


def fetch_point(lat, lon, timeout=60):
    """0-30 cm weighted means in conventional units, or None on failure."""
    params = [('lat', lat), ('lon', lon), ('value', 'mean')]
    params += [('property', p) for p in PROPERTIES]
    params += [('depth', d) for d, _ in DEPTHS]
    resp = requests.get(URL, params=params, timeout=timeout)
    resp.raise_for_status()
    out = {}
    for layer in resp.json()['properties']['layers']:
        factor = layer['unit_measure']['d_factor']
        weights = dict(DEPTHS)
        total = wsum = 0.0
        for depth in layer['depths']:
            value = depth['values'].get('mean')
            if value is None:
                continue
            w = weights.get(depth['label'], 0)
            total += value / factor * w
            wsum += w
        out[layer['name']] = total / wsum if wsum else None
    if all(v is None for v in out.values()):
        return None
    # After d_factor: sand/silt/clay are %, pH is pH, soc is g/kg.
    # Organic matter % = SOC g/kg / 10 x 1.724 (van Bemmelen).
    soc = out.get('soc')
    return {'sand': out.get('sand'), 'silt': out.get('silt'),
            'clay': out.get('clay'), 'ph': out.get('phh2o'),
            'om': soc / 10.0 * 1.724 if soc is not None else None}
