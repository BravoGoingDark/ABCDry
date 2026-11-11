"""Compute today's analysis-map tiles in advance, so the first visitor does not wait.

    python manage.py warm_map_layers                  # all layers, zooms 9-11
    python manage.py warm_map_layers --layers rain spi --zooms 9 10

Tiles are cached per day (see services/sentinel_tiles); run once each morning.
"""
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand, CommandError

from dashboard.services import sentinel_tiles as st


class Command(BaseCommand):
    help = "Pre-compute today's NDVI / NDWI / temperature / rainfall / SPI map tiles over the basin."

    def add_arguments(self, parser):
        parser.add_argument('--layers', nargs='+', default=list(st.LAYERS), choices=list(st.LAYERS))
        parser.add_argument('--zooms', nargs='+', type=int, default=[9, 10, 11])

    def handle(self, *args, layers, zooms, **opts):
        w, s, e, n = st.basin_bounds()
        for layer in layers:
            tiles = []
            for z in zooms:
                if z > st.LAYERS[layer]['max_zoom']:
                    continue
                x0, y0 = st.lonlat_to_tile(w, n, z)
                x1, y1 = st.lonlat_to_tile(e, s, z)
                tiles += [(z, x, y) for x in range(int(x0), int(x1) + 1) for y in range(int(y0), int(y1) + 1)]
            try:
                with ThreadPoolExecutor(8) as pool:
                    list(pool.map(lambda t: st.tile_values(layer, *t), tiles))
            except st.SentinelUnavailable as exc:
                raise CommandError(str(exc))
            self.stdout.write(self.style.SUCCESS(f'{layer}: {len(tiles)} tiles ready'))
