from . import backend_app as backend_app
from .extended_features import register_extended_features
from .promo_notify import register_promo_notify
from .instant_notifications import register_instant_notifications

register_extended_features(backend_app.app)
register_promo_notify(backend_app.app)
register_instant_notifications()
