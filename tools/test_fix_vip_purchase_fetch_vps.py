"""Isolated smoke tests for the targeted VIP CORS fix installer."""
import importlib.util
from pathlib import Path

source = Path(__file__).resolve().parent / "fix_vip_purchase_fetch_vps.py"
spec = importlib.util.spec_from_file_location("nyan_vip_fetch_fix", source)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

extended = (
    "async def create_spend_request(\n"
    "    x_vip_purchase_key: str | None = Header(default=None, alias=\"X-VIP-Purchase-Key\"),\n"
    "):\n"
    "    vip_key = (x_vip_purchase_key or \"\").strip() if is_vip else \"\"\n"
    "    activate_vip(session, item.id, user.telegram_id, timestamp)\n"
)
expected = mod.patched_extended(extended)
assert "    vip_purchase_key: str | None = None," in expected
assert "vip_key = (vip_purchase_key or x_vip_purchase_key or \"\")" in expected
assert mod.patched_extended(expected) == expected
compile(expected, "server/extended_features.py", "exec")

cors = (
    "app.add_middleware(\n"
    "    CORSMiddleware,\n"
    '    allow_headers=["Content-Type", "X-Telegram-Init-Data"],\n'
    ")\n"
)
updated_cors = mod.patched_cors(cors)
assert '"X-VIP-Purchase-Key"' in updated_cors
assert mod.patched_cors(updated_cors) == updated_cors
compile(updated_cors, "server/backend_app.py", "exec")

try:
    mod.patched_extended("def unrelated():\n    return True\n")
except RuntimeError:
    pass
else:
    raise AssertionError("Unrelated source must not be modified")

print("VIP purchase fetch patch is idempotent, isolated and syntax-safe")
