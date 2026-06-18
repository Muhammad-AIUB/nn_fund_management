# Architecture — NN Fund Management

This document explains how the module is structured, how balances are computed,
and how the "money can only be used once" guarantee is enforced.

## 1. Models at a glance

```
nn.fund.account        Bank/cash account. Holds received money.
  └─ nn.incoming.fund   Money received (draft → confirmed → cancelled)

nn.project   ┐  "fund targets" — money is allocated to them, reserved,
nn.expense.head ┘  spent and transferred between them

nn.fund.allocation     Account  → target   (assign unassigned funds)
nn.fund.requisition    target   → (bills)   (reserve funds to spend)
nn.bill                draws down an approved requisition (spend)
nn.fund.transfer       target   → target    (move funds)

nn.approval.history    Immutable audit log (generic res_model/res_id link)

# Abstract mixins (no table, pure reuse)
nn.fund.target.mixin   All balance fields + the balance formula
nn.approval.mixin      GM→MD workflow, permission checks, history, hooks
```

The two **mixins** are the heart of the design — they hold logic shared across
several concrete models so the rules are written once.

## 2. The balance model (single source of truth)

A fund target (project or expense head) exposes these **computed, stored,
read-only** fields, all produced by one method in `nn.fund.target.mixin`:

```
available_fund =
      total_allocated          # approved allocations in
    + incoming_transfer        # approved transfers in
    - outgoing_transfer        # approved transfers out
    - requisition_hold         # requisitions pending approval
    - transfer_hold            # outgoing transfers pending approval
    - approved_unspent         # approved requisitions' remaining billable
    - total_spent              # posted bills
```

A fund **account** has an analogous formula:

```
available_balance = total_received - on_hold_amount - assigned_amount
```

where `total_received` = confirmed incoming funds, `on_hold_amount` =
allocations *pending* approval, `assigned_amount` = *approved* allocations.

### Why compute from state?

Each component is derived from the **state of related documents**, not from
running totals that get incremented/decremented. This is the key decision:

- There is no "balance += amount" code anywhere, so there is nothing to run
  twice. A balance is always a pure function of the documents that exist.
- Approving a request twice is impossible (state guards), and even if a method
  were called twice, the computed balance would be identical.

`nn.fund.target.mixin._get_balance_components()` reads `allocation_ids`,
`requisition_ids`, `transfer_in_ids`, `transfer_out_ids` — relations that both
`nn.project` and `nn.expense.head` declare under **identical field names**, so
the maths lives in one place. Each concrete model only declares the relations
plus an `@api.depends(...)` override so Odoo knows when to recompute.

## 3. How double-spending is prevented

| Stage | Effect on balance | Mechanism |
|-------|-------------------|-----------|
| Allocation submitted | account *on hold* | counted by state `submitted/gm_approved` |
| Allocation approved | account *assigned*, target *allocated* | state `approved` |
| Requisition submitted | target *requisition_hold* | pending states |
| Requisition approved | target *approved_unspent* (= remaining billable) | state `approved` |
| Bill posted | target *spent*, requisition remaining ↓ | posted bills summed |
| Transfer submitted | source *transfer_hold* | pending states |
| Transfer approved | source *outgoing*, dest *incoming* | state `approved` |

Held money is excluded from `available_*`, so it cannot be picked up by a second
request. Server-side checks (`_check_can_submit`) refuse to submit anything that
exceeds the current available balance. Reversing a posted bill simply drops it
out of the "posted bills" sum — it restores the remaining billable and **never
creates new funds**.

## 4. The reusable approval engine (`nn.approval.mixin`)

Allocations, requisitions and transfers all `_inherit` this mixin, which
provides:

- **State machine:** `draft → submitted → gm_approved → approved`, plus
  `rejected` / `cancelled` (requisition adds `closed` via `selection_add`).
- **GM before MD:** MD can only act once the state is `gm_approved`; the state
  itself enforces ordering.
- **Server-side approver check:** `approve()`/`reject()` verify the user is in
  the level's group (`group_gm_approver` / `group_md_approver`).
- **No self-approval:** blocked unless the `allow_self_approval` config option
  is set (Settings screen).
- **Idempotency:** every transition is guarded by the current state, so a double
  click raises a `UserError` instead of moving money twice.
- **Audit:** each transition writes an immutable `nn.approval.history` row
  (creator, approver, level, from/new status, date, comment, amount, related
  account/project/expense head). Rows are written with `sudo()` and are not
  user-deletable.
- **Extensibility hooks:** `_check_can_submit`, `_on_submit`,
  `_on_final_approve`, `_on_reject`, `_on_cancel` let each document add its own
  validation/effects without touching the workflow.

The approve/reject **comment** is captured via a tiny transient wizard
(`nn.approval.wizard`); a reason is mandatory on rejection.

## 5. Security layers (defense in depth)

1. **ACLs** (`ir.model.access.csv`) — per model × group CRUD.
2. **Record rules** — global multi-company rule on every model.
3. **Method-level checks** — approver group, self-approval, finance-only
   confirmation of incoming funds, admin-only cancellation of approved docs.
4. **`@api.ondelete` guards** — confirmed/posted documents can't be deleted.

Hiding buttons in the UI is treated as cosmetic only; every rule above holds
even when a model is poked directly via RPC or the shell.

## 6. Extending the workflow

- **Add/remove an approval level:** the workflow is centralized in
  `nn.approval.mixin`. A third level would add a state and an `approve()` branch
  in one place, inherited by all three document types.
- **Change who can approve:** add/remove users in the GM/MD groups — no code.
- **New document type:** inherit `nn.approval.mixin` + `mail.thread`, implement
  `_check_can_submit` and `_approval_log_extra`, and it gets the whole workflow,
  history and permission model for free.
