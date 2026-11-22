#!/usr/bin/env python3
"""Install the complete original VIP kit into an existing nyan-wallet checkout.

Safe to run repeatedly. Preserves unrelated local changes and refuses to
silently overwrite unknown anchors. Does not run git push or deploy to VPS.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def patch_once(text: str, anchor: str, replacement: str, marker: str, name: str) -> str:
    if marker in text:
        return text
    if anchor not in text:
        raise ValueError(f"{name}: expected anchor not found: {anchor[:50]!r}")
    if text.count(anchor) != 1:
        raise ValueError(f"{name}: expected anchor occurs {text.count(anchor)} times")
    return text.replace(anchor, replacement, 1)


def build_edits(checkout: Path) -> dict[Path, str]:
    edits = {}
    init_path = checkout / 'server' / '__init__.py'
    index_path = checkout / 'index.html'
    appeal_path = checkout / 'server' / 'appeals.py'
    card_path = checkout / 'nyan_id.js'

    init = init_path.read_text(encoding='utf-8')
    init = patch_once(init,
        'from .vip import register_vip\n',
        'from .vip import register_vip\nfrom .vip_plus import register_vip_plus\n',
        'from .vip_plus import register_vip_plus', 'server/__init__.py')
    init = patch_once(init,
        '    register_vip(backend_app.app)\n',
        '    register_vip(backend_app.app)\n    register_vip_plus(backend_app.app)\n',
        'register_vip_plus(backend_app.app)', 'server/__init__.py')
    edits[init_path] = init

    index = index_path.read_text(encoding='utf-8')
    index = patch_once(index,
        '    <link rel="stylesheet" href="./vip.css?v=20261122-vip1">',
        '    <link rel="stylesheet" href="./vip.css?v=20261122-vip1">\n'
        '    <link rel="stylesheet" href="./vip-plus.css?v=20261122-kit1">',
        'vip-plus.css', 'index.html')
    index = patch_once(index,
        '<script src="./vip.js?v=20261122-vip-fetch2"></script>',
        '<script src="./vip.js?v=20261122-vip-fetch2"></script>\n'
        '<script src="./vip-plus.js?v=20261122-kit1"></script>',
        'vip-plus.js', 'index.html')
    edits[index_path] = index

    appeals = appeal_path.read_text(encoding='utf-8')
    anchor = '        rows = session.execute(stmt.order_by(Appeal.updated_at.desc()).limit(200)).all()'
    replacement = '''        # Active VIP appeals are prioritised without excluding regular users.
        from .vip import VipSubscription
        priority = (
            select(VipSubscription.request_id)
            .where(
                VipSubscription.telegram_id == Appeal.telegram_id,
                VipSubscription.starts_at <= now_utc(),
                VipSubscription.ends_at > now_utc(),
                Appeal.status.in_(OPEN_APPEAL_STATUSES),
            )
            .correlate(Appeal).exists()
        )
        rows = session.execute(stmt.order_by(priority.desc(), Appeal.updated_at.desc()).limit(200)).all()
        active_vip_ids = set(session.scalars(select(VipSubscription.telegram_id).where(
            VipSubscription.starts_at <= now_utc(),
            VipSubscription.ends_at > now_utc(),
        )).all())'''
    appeals = patch_once(appeals, anchor, replacement, 'active_vip_ids = set(', 'server/appeals.py')
    appeals = patch_once(appeals,
        '                "message_preview": item.message[:220],',
        '                "message_preview": item.message[:220],\n'
        '                "vip_priority": item.telegram_id in active_vip_ids and item.status in OPEN_APPEAL_STATUSES,',
        '"vip_priority": item.telegram_id in active_vip_ids', 'server/appeals.py')
    edits[appeal_path] = appeals

    card = card_path.read_text(encoding='utf-8')
    anchor = '    const canvas = drawCard();\n    return await new Promise((resolve, reject) => {'
    replacement = '''    const canvas = drawCard();
    if (identity?.vip?.active) {
      // Export the ORIGINAL VIP status asset on the shared Nyan ID PNG.
      const logo = new Image();
      logo.src = "./assets/vip/04_vip_small_label.png";
      try { await logo.decode(); } catch (_) {}
      if (logo.naturalWidth) canvas.getContext("2d")?.drawImage(logo, 996, 150, 100, 58);
    }
    return await new Promise((resolve, reject) => {'''
    card = patch_once(card, anchor, replacement, 'Export the ORIGINAL VIP status asset', 'nyan_id.js')
    edits[card_path] = card
    return edits


def main() -> None:
    parser = argparse.ArgumentParser(description='Install Nyan VIP kit into a wallet repo checkout')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--check', action='store_true', help='check anchors without writing')
    args = parser.parse_args()
    checkout = args.repo.resolve()
    if not (checkout / 'index.html').is_file() or not (checkout / 'server' / 'vip.py').is_file():
        parser.error('--repo must point at the nyan-wallet repository root')
    edits = build_edits(checkout)
    paths = {
        checkout / 'vip-plus.js': ROOT / 'vip-plus.js',
        checkout / 'vip-plus.css': ROOT / 'vip-plus.css',
        checkout / 'server' / 'vip_plus.py': ROOT / 'server' / 'vip_plus.py',
        checkout / 'bot_addons' / 'nyan_shop_vip_cashback.py': ROOT / 'bot_addons' / 'nyan_shop_vip_cashback.py',
    }
    images = sorted((ROOT / 'assets' / 'vip').glob('*.png'))
    if len(images) != 17:
        parser.error('expected all 17 original PNG files in assets/vip')
    paths.update({checkout / 'assets' / 'vip' / f.name: f for f in images})
    for target, source in paths.items():
        if target.is_file() and target.read_bytes() != source.read_bytes():
            parser.error(f'refusing to replace conflicting file: {target}')
    if args.check:
        print(f'OK: {len(edits)} integration edits and {len(paths)} original/new files')
        return
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    backup = checkout / '.nyan-vip-backup' / stamp
    backup.mkdir(parents=True, exist_ok=False)
    for target in edits:
        dest = backup / target.relative_to(checkout)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
    try:
        for target, content in edits.items():
            target.write_text(content, encoding='utf-8')
        for target, source in paths.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    except Exception:
        for target in edits:
            shutil.copy2(backup / target.relative_to(checkout), target)
        for target, source in paths.items():
            if target.is_file() and target.read_bytes() == source.read_bytes():
                target.unlink()
        raise
    print(f'Installed {len(images)} original VIP PNG files and source changes.')
    print(f'Backup: {backup}')
    print('IMPORTANT: server changes require a safe deployment of FastAPI; upload code alone is not live.')
    print('Before running anything against production, review changes with git diff and run tests.')


if __name__ == '__main__':
    main()
