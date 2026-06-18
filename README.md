# NN Fund Management

A custom Odoo module for **NN Services & Engineering Ltd.** that manages the
full lifecycle of company funds — incoming funds, allocations to projects and
expense heads, requisitions, bills, and transfers — under a two-level
(GM → MD) approval workflow with strict, computed balance control.

> **Core guarantee:** the same money can never be allocated, transferred or
> spent more than once. Every balance is *computed* from document state, so a
> repeated click or a stale screen can never double-move funds.

---

## Odoo version

- **Odoo 17.0** (Community)
- **PostgreSQL 15**
- **Python 3** (runs inside the official `odoo:17.0` image)

---

## Required dependencies

The module depends only on standard Odoo apps (installed automatically):

| Dependency | Why |
|------------|-----|
| `base` | core framework |
| `mail` | chatter, activities, audit tracking on documents |

No third-party Python packages are required. Everything else (Docker images)
is declared in `docker-compose.yml`.

---

## Installation

The project is fully dockerized. From the repository root:

```bash
docker compose up -d
```

This starts two containers:

- `db` — PostgreSQL 15
- `odoo` — Odoo 17 with this repo's `addons/` mounted at `/mnt/extra-addons`

Then open **http://localhost:8069**.

### First-time setup

1. Create a database (or let Odoo create one) and **install the module**:
   - Easiest (clean DB named `odoo`):
     ```bash
     docker compose run --rm odoo odoo -d odoo -i nn_fund_management --stop-after-init
     docker compose up -d
     ```
   - Or from the UI: log in, enable Developer Mode, go to **Apps**,
     *Update Apps List*, search **NN Fund Management**, click **Install**.
2. On install, a `post_init_hook` grants the default **admin** user the
   *Fund Administrator* role, so the **Fund Management** app is immediately
   visible and usable.

### Upgrading the module after code changes

```bash
docker compose run --rm odoo odoo -d odoo -u nn_fund_management --stop-after-init
docker compose up -d
```

---

## Configuration steps

1. **Assign roles.** *Settings → Users* — give each user one or more module
   groups (see [Security](#security--access-control)). Approvers are defined by
   group membership, **not** hardcoded, so you can add/remove approvers freely.
2. **Self-approval policy.** *Fund Management → Configuration → Settings* —
   toggle **Allow Self-Approval**. Off by default (segregation of duties); when
   off, a user can never approve a request they created.
3. **Create master data.** Under *Configuration*: create **Fund Accounts**,
   **Projects**, and **Expense Heads**. Five common expense heads (rent, salary,
   utilities, marketing, admin) are seeded on install.

---

## Usage (typical flow)

1. **Incoming Funds** → record money received → **Confirm** (Finance only).
   The amount joins the account's *unassigned* balance.
2. **Fund Allocations** → assign unassigned funds to a project or expense head.
   Submit → GM → MD. While pending the money is *on hold*; once approved it is
   *assigned* to the target.
3. **Fund Requisitions** → request funds from a project/expense head. Approved
   requisitions reserve money for bills.
4. **Bills** → draw down an approved requisition (partial bills allowed).
5. **Fund Transfers** → move funds between projects/expense heads.
6. **Reporting → Approval / Audit History** → full immutable trail.

---

## Testing instructions

The module ships **22 automated tests** (unit/integration) covering balance
maths, double-spend prevention, approval rules and all server-side blocks.

Run them on a throwaway database:

```bash
docker compose run --rm odoo odoo -d test_nn -i nn_fund_management \
  --test-enable --test-tags /nn_fund_management --stop-after-init
```

Expected result: `0 failed, 0 error(s) of 22 tests`.

> On Git Bash / MSYS, prefix the command with `MSYS_NO_PATHCONV=1` so the
> `/nn_fund_management` test tag isn't rewritten into a Windows path.

### Manual demonstration (the assessment scenario)

Receive 1,000,000 → allocate 600,000 to Project A (shows on hold) → reject
(money returns) → re-allocate & approve → transfer 200,000 A→B (held, then
approved) → requisition 150,000 on B → bill 100,000 (50,000 remains) → try to
bill 60,000 (blocked) → try to bill Project A against B's requisition
(blocked). All of these are also asserted by the automated tests.

---

## Security & access control

Five configurable groups:

| Group | Can do |
|-------|--------|
| **Fund User** | create/view requests (allocations, requisitions, bills, transfers) |
| **Finance User** | + manage fund accounts, **confirm incoming funds** |
| **GM Approver** | first-level approval |
| **MD Approver** | second-level approval |
| **Fund Administrator** | full control; can cancel approved documents |

Enforcement is **server-side**, not just hidden buttons:

- ACLs (`ir.model.access.csv`) per model and group.
- **Multi-company record rules** — users can't see other companies' records.
- Workflow methods check the approver group, block self-approval, and enforce
  GM-before-MD. Hiding a button is never the only protection.

---

## Architecture

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the model map, the balance
formula, how double-spending is prevented, and the reusable approval engine.

---

## Assumptions

- All amounts are in the **company currency** (BDT in the demo). No
  cross-currency conversion.
- A **fund user is an internal employee** (the group implies *Internal User*).
- "Configurable approvers" is implemented via **security groups**; any user in
  the GM/MD group can act at that level. Per-amount approval matrices are noted
  as a bonus, not implemented in the core.
- The **bill** is a custom model (`nn.bill`) rather than an integration with
  Odoo Vendor Bills, to keep the fund-control rules self-contained and explicit.
- Balances are **stored computed fields**; they recompute automatically from the
  contributing documents and are never editable by hand.

---

## Known limitations

- The unique transaction-reference constraint is per *(fund account, reference)*
  and also reserves the reference of a *cancelled* incoming fund.
- No cross-currency / multi-currency support.
- Bank-email ingestion, the configurable per-amount approval matrix, and the
  graphical dashboard described in the brief are **bonus** items and are not
  included in this submission.
- `post_init_hook` grants admin access on **install**; on an *upgrade* of a DB
  where groups were first created under `noupdate`, group definition changes may
  need a fresh install to fully apply (fresh installs are unaffected).
- Reporting is provided as list views + the audit history; no PDF reports.

---

## Project structure

```
.
├── addons/
│   └── nn_fund_management/
│       ├── models/          # business models + mixins
│       ├── wizard/          # approval decision dialog
│       ├── views/           # tree/form/menus/settings
│       ├── security/        # groups, ACLs, record rules
│       ├── data/            # sequences, default expense heads
│       ├── tests/           # 22 automated tests
│       └── static/description/icon.png
├── docker-compose.yml       # Odoo 17 + Postgres 15
├── README.md
└── ARCHITECTURE.md
```
