from app.connectors.web.connector import WebConnector


class MetaConnector(WebConnector):
    """Indexed Facebook discovery and accessible public HTML only; no login bypass."""
    platform='meta'
    domains=('facebook.com',)
    version='1-facebook-public-web'
