from __future__ import unicode_literals
import warnings

from freedom.conf.urls.i18n import i18n_patterns
from freedom.http import HttpResponse, StreamingHttpResponse
from freedom.utils.translation import ugettext_lazy as _


# test deprecated version of i18_patterns() function (with prefix). Remove it
# and convert to list of urls() in Freedom 2.0
with warnings.catch_warnings(record=True):
    warnings.filterwarnings('ignore', module='freedom.conf.urls.18n')

    urlpatterns = i18n_patterns('',
        (r'^simple/$', lambda r: HttpResponse()),
        (r'^streaming/$', lambda r: StreamingHttpResponse([_("Yes"), "/", _("No")])),
    )
