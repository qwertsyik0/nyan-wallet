import os

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL отсутствует: Nyan Wallet не запускается без постоянной PostgreSQL базы")

if not DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("DATABASE_URL должен указывать на PostgreSQL")

from . import backend_app as backend_app
from .root_health import register_root_health
from .extended_features import register_extended_features
from .promo_notify import register_promo_notify
from .campaign_promos import register_campaign_promos
from .limited_promos import register_limited_promos
from .instant_notifications import register_instant_notifications
from .advanced_features import register_advanced_features
from .referral_fix import register_referral_fix
from .release_hardening import register_release_hardening
from .achievements import register_achievements
from .activity import register_activity
from .daily_tasks import register_daily_tasks
from .daily_tasks_defaults_v2 import register_daily_tasks_defaults_v2
from .daily_task_hooks import register_daily_task_hooks
from .giveaways import register_giveaways
from .appeals import register_appeals
from .transfers import register_transfers
from .broadcast import register_broadcast
from .maintenance import register_maintenance

register_campaign_promos()
register_limited_promos(backend_app.app)
register_root_health(backend_app.app)
register_extended_features(backend_app.app)
register_promo_notify(backend_app.app)
register_instant_notifications()
register_advanced_features(backend_app.app)
register_referral_fix(backend_app.app)
register_release_hardening(backend_app.app)
register_achievements(backend_app.app)
register_activity(backend_app.app)
register_daily_tasks(backend_app.app)
register_daily_tasks_defaults_v2()
register_daily_task_hooks()
register_giveaways(backend_app.app)
register_appeals(backend_app.app)
register_transfers(backend_app.app)
register_broadcast(backend_app.app)
register_maintenance(backend_app.app)
