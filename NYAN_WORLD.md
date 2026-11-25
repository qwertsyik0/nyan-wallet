# NYAN WORLD

Politics, embassies, courts and public statements stay in Telegram. Nyan Wallet stores separate state budgets and written requests. The organizer sets every consequence; there is no automatic simulation and no exchange with lapcoins.

## Owner workflow

1. Open NYAN WORLD from the wallet and create a season. It starts as a draft unless you select a different status.
2. Set the name, fictional currency, rules and Telegram chat link. Select the current season.
3. Add countries, initial budgets, leaders, indicators, income, expenses and debt. Assign one Telegram ID per country or open registration. A player must have opened Nyan Wallet first.
4. Review written requests. Approve, reject or return for revision with a comment.
5. For approved requests set a budget delta, indicators, income, expenses, debt and optional transfer recipient. Approval records these values without moving money.
6. Apply consequences explicitly. Planned dates are reminders, not automatic execution.
7. Use the budget panel for manual funding, debits, transfers and income/expense period calculations.
8. Correct financial mistakes with a reverse operation. Both sides of a transfer are reversed together. If funds were already spent, restore sufficient funds first; negative balances are blocked.
9. Pause or finish seasons. Old seasons remain available to the owner. No historical records are deleted.

Country settings replace the displayed indicator set. Request effects update only the named indicators. Notes in country settings are visible to that country's current player. Budget histories are private to the owner and assigned player. Request histories are private to their author and owner.

## Safety

All actions require existing Telegram Mini App authentication. Owner permissions are enforced server-side. All writes are serialized by the singleton settings row in PostgreSQL and audited. UUID operation IDs make retries idempotent; each form retains its ID after a network error. Every budget mutation has a ledger entry. World tables use the nw_ prefix and never update wallet users.balance or transactions.

Financial reversals do not undo nonfinancial indicator changes; edit those explicitly. Income and expense periods are manual, and a new confirmed calculation is a new operation. Do not confirm the same period twice as two different actions.

The cabinet shows the latest 300 requests and budget operations and the latest 200 administrative actions; full records remain in the database. Notifications are in the world cabinet, not a Telegram broadcast. Actual publication of approved announcements stays in the event chat.

## Installation on the existing VPS

Run tools/install_nyan_world.py --ref COMMIT_SHA as root. It downloads version-pinned new files, adds the registration and entry hooks while preserving local code, backs up files, restarts the API and checks both health and World routes. On failure it restores code. Additive world tables may remain after a failed installation and are not dropped.

The installer does not populate real-world countries or leaders. All starting conditions are configured by the owner.

## Tests

.github/workflows/nyan-world.yml validates Python and JavaScript syntax and tests authentication, permissions, data isolation, idempotence, atomic transfers, reversal, moderation, revisions, assignment uniqueness, registration, paused seasons and rollback on insufficient funds.
