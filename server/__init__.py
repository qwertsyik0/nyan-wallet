import os

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL отсутствует: Nyan Wallet не запускается без постоянной PostgreSQL базы")

if not DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("DATABASE_URL должен указывать на PostgreSQL")

from . import backend_app as backend_app
from .quote_reflection import register_quote_reflection
from .root_health import register_root_health
from .extended_features import register_extended_features
from .promo_notify import register_promo_notify
from .campaign_promos import register_campaign_promos
from .limited_promos import register_limited_promos
from .instant_notifications import register_instant_notifications
from .telegram_relay import register_telegram_relay
from .advanced_features import register_advanced_features
from .referral_fix import register_referral_fix
from .release_hardening import register_release_hardening
from .achievements import register_achievements
from .nyan_id import register_nyan_id
from .activity import register_activity
from .daily_tasks import register_daily_tasks
from .daily_tasks_defaults_v2 import register_daily_tasks_defaults_v2
from .daily_task_hooks import register_daily_task_hooks
from .giveaways import register_giveaways
from .appeals import register_appeals
from .transfers import register_transfers
from .antifraud import register_antifraud
from .recent_transfers_20261011 import print_recent_wallet_transfers_20261011
from .broadcast import register_broadcast
from .maintenance import register_maintenance
from .wallet_survey import register_wallet_survey
from .suggestions import register_suggestions
from .interactive_ideas import register_interactive_ideas
from .interactive_builder import register_interactive_builder
from .profile_overview import register_profile_overview
from .finance_analytics import register_finance_analytics
from .finance_recruitment import register_finance_recruitment
from .finance_stage2 import register_finance_stage2
from .finance_workspace import register_finance_workspace
from .elections import register_elections
from .elections_voting import register_elections_voting
from .bot_menu import sync_bot_menu_buttons
from .user_bans import register_user_bans
from .promo_delayed_fee import register_promo_delayed_fee
from .manual_grants_20261004 import apply_interactive_grants_20261004
from .manual_grants_20261004_backfill import backfill_interactive_grants_20261004
from .manual_request_35_animated_bg import apply_request_35_animated_profile_background
from .apology_promo_20261009 import ensure_apology_promo_20261009
from .verify_request35_bg import verify_request35_background
from .catalog_reprice_20261007 import apply_catalog_reprice_20261007
from .nyan_market_leftover_exchange_20261011 import apply_nyan_market_leftover_exchange_20261011
from .survey_channel_followups_20261011 import send_survey_channel_followups_20261011

# Restore-time schema build: register all ORM models without running grants,
# Telegram calls, notification workers or other startup side effects.
if os.getenv("NYAN_RESTORE_SCHEMA_ONLY") == "1":
    backend_app.Base.metadata.create_all(backend_app.engine)
else:
    register_campaign_promos()
    apply_interactive_grants_20261004()
    backfill_interactive_grants_20261004()
    register_limited_promos(backend_app.app)
    register_root_health(backend_app.app)
    register_extended_features(backend_app.app)
    register_promo_notify(backend_app.app)
    register_instant_notifications()
    register_advanced_features(backend_app.app)
    register_telegram_relay(backend_app.app)
    apply_request_35_animated_profile_background()
    ensure_apology_promo_20261009()
    verify_request35_background()
    apply_catalog_reprice_20261007()
    apply_nyan_market_leftover_exchange_20261011()
    register_referral_fix(backend_app.app)
    register_release_hardening(backend_app.app)
    register_achievements(backend_app.app)
    register_nyan_id(backend_app.app)
    register_activity(backend_app.app)
    register_daily_tasks(backend_app.app)
    register_daily_tasks_defaults_v2()
    register_daily_task_hooks()
    register_giveaways(backend_app.app)
    register_appeals(backend_app.app)
    register_transfers(backend_app.app)
    register_antifraud(backend_app.app)
    print_recent_wallet_transfers_20261011()
    register_broadcast(backend_app.app)
    register_maintenance(backend_app.app)
    register_quote_reflection(backend_app.app)
    register_suggestions(backend_app.app)
    register_interactive_ideas(backend_app.app)
    register_interactive_builder(backend_app.app)
    register_profile_overview(backend_app.app)
    register_finance_analytics(backend_app.app)
    # 2026-10-19: Elections, the old wallet survey and financial-admin
    # recruitment are retired. Keep ORM module imports above for safe schema
    # restoration and keep finance_workspace for active trainees/requests.
    register_finance_workspace(backend_app.app)
    register_user_bans(backend_app.app)
    register_promo_delayed_fee(backend_app.app)
    sync_bot_menu_buttons()
    
