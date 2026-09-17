import os

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL отсутствует: Nyan Wallet не запускается без постоянной PostgreSQL базы")

if not DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("DATABASE_URL должен указывать на PostgreSQL")

from . import backend_app as backend_app
from .extended_features import register_extended_features
from .promo_notify import register_promo_notify
from .instant_notifications import register_instant_notifications
from .advanced_features import register_advanced_features

register_extended_features(backend_app.app)
register_promo_notify(backend_app.app)
register_instant_notifications()
register_advanced_features(backend_app.app)
