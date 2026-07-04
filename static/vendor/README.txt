Vendor assets are loaded from CDN in development (templates/base/cdn_refs.html).

To bundle locally for offline use, run the download script:
    python manage.py download_vendor_assets

This places files under static/vendor/ and switches the base template
to load from STATIC_URL instead of CDN.
