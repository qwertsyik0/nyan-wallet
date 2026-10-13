from sqlalchemy import select
from . import backend_app as core
from .promo150_subscription_penalty import Promo150SubscriptionWatch

TARGETS = [
    (5786401764, "desirabletarget"),
    (8256340108, "rosws"),
    (6651466766, "liviskas"),
    (5157841885, "Sakaighezd"),
    (7316515864, "Maknylya"),
    (8398531040, "fgbb7"),
    (6369149798, "daikon_yashiro"),
    (6613389408, "noksaaaa"),
    (5124338391, "x_x_AoiA0_x_x"),
    (5178423819, "mach6rie"),
    (7955773521, "flammei"),
    (6141474108, "CopiaCardinal"),
    (8253319388, "Happy_Ananass"),
    (5309907378, "k4r11_xD"),
    (6606659803, "w1xckkxk"),
    (5291356933, ".sofiyusheva"),
    (7858173019, "SUGA_KO"),
    (8932587757, "tesoro_weet"),
    (5806003261, "weevtt"),
    (6528201214, "Gylhl"),
    (6188280497, "Scarecrow_I"),
    (8547364108, "zxbonsf"),
    (5414078028, "Stolas_024"),
    (8692747898, "Ceniora_vanil"),
    (8293528135, "reveriieeii"),
    (6453256342, "floriannq"),
    (7723488357, "mppwb"),
    (6968551476, "PIXEL_ARE_YOU_OKAY"),
    (5406023396, "Mrs_corner"),
    (7267328440, "rc_otq"),
    (6737323349, "ari"),
    (5354595027, "vampr1kski"),
    (1129986805, "nasttchl"),
    (5422590457, "urbzk"),
    (6289461565, "Qwertsyiks"),
]

def print_promo150_subscription_report_20261013() -> None:
    with core.SessionLocal() as session:
        promo = session.scalar(select(core.PromoCode).where(core.PromoCode.code == "NYAN150"))
        promo_id = promo.id if promo else None
        for telegram_id, label in TARGETS:
            try:
                status = core._channel_subscription_status(telegram_id)
                subscribed = bool(status.get("subscribed"))
                tg_status = status.get("status")
            except Exception as exc:
                subscribed = None
                tg_status = f"ERROR:{type(exc).__name__}"

            watch = None
            if promo_id is not None:
                watch = session.scalar(
                    select(Promo150SubscriptionWatch).where(
                        Promo150SubscriptionWatch.promo_id == promo_id,
                        Promo150SubscriptionWatch.telegram_id == telegram_id,
                    )
                )
            print(
                "[promo150_check] "
                f"id={telegram_id} label={label} "
                f"subscribed={subscribed} tg_status={tg_status} "
                f"watch={'yes' if watch else 'no'} "
                f"last_checked={watch.last_checked_at.isoformat() if watch and watch.last_checked_at else None} "
                f"penalized={bool(watch and watch.penalized_at)} "
                f"penalized_at={watch.penalized_at.isoformat() if watch and watch.penalized_at else None} "
                f"penalty={watch.penalty_amount if watch else None}"
            )
