from __future__ import unicode_literals

from unittest import skipUnless

from django.contrib.gis.geos import HAS_GEOS
from django.contrib.gis.tests.utils import HAS_SPATIAL_DB
from django.test import TestCase, override_settings

if HAS_GEOS and HAS_SPATIAL_DB:
    from django.contrib.gis import admin
    from django.contrib.gis.geos import Point

    from .admin import UnmodifiableAdmin
    from .models import City


@skipUnless(HAS_GEOS and HAS_SPATIAL_DB, "Geos and spatial db are required.")
@override_settings(ROOT_URLCONF='django.contrib.gis.tests.geoadmin.urls')
class GeoAdminTest(TestCase):

    def test_ensure_geographic_media(self):
        geoadmin = admin.site._registry[City]
        admin_js = geoadmin.media.render_js()
        self.assertTrue(any(geoadmin.openlayers_url in js for js in admin_js))

    def test_olmap_OSM_rendering(self):
        delete_all_btn = """<a href="javascript:geodjango_point.clearFeatures()">Delete all Features</a>"""

        original_geoadmin = admin.site._registry[City]
        params = original_geoadmin.get_map_widget(City._meta.get_field('point')).params
        result = original_geoadmin.get_map_widget(City._meta.get_field('point'))(
        ).render('point', Point(-79.460734, 40.18476), params)
        self.assertIn(
            """geodjango_point.layers.base = new OpenLayers.Layer.OSM("OpenStreetMap (Mapnik)");""",
            result)

        self.assertIn(delete_all_btn, result)

        admin.site.unregister(City)
        admin.site.register(City, UnmodifiableAdmin)
        try:
            geoadmin = admin.site._registry[City]
            params = geoadmin.get_map_widget(City._meta.get_field('point')).params
            result = geoadmin.get_map_widget(City._meta.get_field('point'))(
            ).render('point', Point(-79.460734, 40.18476), params)

            self.assertNotIn(delete_all_btn, result)
        finally:
            admin.site.unregister(City)
            admin.site.register(City, original_geoadmin.__class__)

    def test_olmap_WMS_rendering(self):
        geoadmin = admin.GeoModelAdmin(City, admin.site)
        result = geoadmin.get_map_widget(City._meta.get_field('point'))(
        ).render('point', Point(-79.460734, 40.18476))
        self.assertIn(
            """geodjango_point.layers.base = new OpenLayers.Layer.WMS("OpenLayers WMS", "http://vmap0.tiles.osgeo.org/wms/vmap0", {layers: \'basic\', format: 'image/jpeg'});""",
            result)

    def test_olwidget_has_changed(self):
        """
        Check that changes are accurately noticed by OpenLayersWidget.
        """
        geoadmin = admin.site._registry[City]
        form = geoadmin.get_changelist_form(None)()
        has_changed = form.fields['point']._has_changed

        initial = Point(13.4197458572965953, 52.5194108501149799, srid=4326)
        data_same = "SRID=3857;POINT(1493879.2754093995 6894592.019687599)"
        data_almost_same = "SRID=3857;POINT(1493879.2754093990 6894592.019687590)"
        data_changed = "SRID=3857;POINT(1493884.0527237 6894593.8111804)"

        self.assertTrue(has_changed(None, data_changed))
        self.assertTrue(has_changed(initial, ""))
        self.assertFalse(has_changed(None, ""))
        self.assertFalse(has_changed(initial, data_same))
        self.assertFalse(has_changed(initial, data_almost_same))
        self.assertTrue(has_changed(initial, data_changed))
