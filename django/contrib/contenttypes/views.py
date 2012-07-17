from __future__ import unicode_literals

from django import http
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site, get_current_site
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import ugettext as _

def shortcut(request, content_type_id, object_id):
    """
    Redirect to an object's page based on a content-type ID and an object ID.
    """
    # Look up the object, making sure it's got a get_absolute_url() function.
    try:
        content_type = ContentType.objects.get(pk=content_type_id)
        if not content_type.model_class():
            raise http.Http404(_("Content type %(ct_id)s object has no associated model") %
                               {'ct_id': content_type_id})
        obj = content_type.get_object_for_this_type(pk=object_id)
    except (ObjectDoesNotExist, ValueError):
        raise http.Http404(_("Content type %(ct_id)s object %(obj_id)s doesn't exist") %
                           {'ct_id': content_type_id, 'obj_id': object_id})

    try:
        get_absolute_url = obj.get_absolute_url
    except AttributeError:
        raise http.Http404(_("%(ct_name)s objects don't have a get_absolute_url() method") %
                           {'ct_name': content_type.name})
    absurl = get_absolute_url()

    # Try to figure out the object's domain, so we can do a cross-site redirect
    # if necessary.

    # If the object actually defines a domain, we're done.
    if absurl.startswith('http://') or absurl.startswith('https://'):
        return http.HttpResponseRedirect(absurl)

    # Otherwise, we need to introspect the object's relationships for a
    # relation to the Site object
    object_domain = None
    current_domain = None

    # Get current site (if possible): this decides the preferred domain
    # if this object has an M2M site field and provides a fallback if this
    # object does not have a site FK or M2M field.
    try:
        current_domain = get_current_site(request).domain
    except Site.DoesNotExist:
        pass

    if Site._meta.installed:
        opts = obj._meta

        # First, look for an many-to-many relationship to Site.
        for field in opts.many_to_many:
            if field.rel.to is Site:
                site_qs = getattr(obj, field.name).all()
                try:
                    # If one of the sites this object belongs to is the current
                    # site, use it.
                    object_domain = site_qs.get(domain=current_domain).domain
                except Site.DoesNotExist:
                    pass
                if object_domain is not None:
                    break
                try:
                    # Current site was not in the M2M relationship for this
                    # object. Caveat: This just selects the *first* one, which
                    # is arbitrary. (Generally based on Site model ordering,
                    # which is alphabetical by domain.)
                    object_domain = site_qs[0].domain
                except IndexError:
                    pass
                if object_domain is not None:
                    break

        # Next, look for a many-to-one relationship to Site.
        if object_domain is None:
            for field in obj._meta.fields:
                if field.rel and field.rel.to is Site:
                    try:
                        object_domain = getattr(obj, field.name).domain
                    except Site.DoesNotExist:
                        pass
                    if object_domain is not None:
                        break

    # Fall back to the current site (if possible) or None (which is fine).
    if object_domain is None:
        object_domain = current_domain

    # If all that malarkey found an object domain, use it. Otherwise, fall back
    # to whatever get_absolute_url() returned.
    if object_domain is not None:
        protocol = request.is_secure() and 'https' or 'http'
        return http.HttpResponseRedirect('%s://%s%s'
                                         % (protocol, object_domain, absurl))
    else:
        return http.HttpResponseRedirect(absurl)
