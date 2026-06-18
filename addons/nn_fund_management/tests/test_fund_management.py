# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError, UserError, ValidationError


@tagged('post_install', '-at_install')
class TestFundManagementCommon(TransactionCase):
    """Shared fixtures: one fund account, two projects, an expense head and a
    full set of role users so the approval rules are tested through the real
    permission paths (not as superuser)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref('base.main_company')

        def make_user(login, group_xmlid):
            return cls.env['res.users'].create({
                'name': login,
                'login': login,
                'email': '%s@example.com' % login,
                # Inbox notifications so the bonus activity/notification paths
                # run without needing an outgoing mail server.
                'notification_type': 'inbox',
                'groups_id': [(6, 0, [cls.env.ref(group_xmlid).id])],
                'company_ids': [(6, 0, [cls.company.id])],
                'company_id': cls.company.id,
            })

        cls.user_fund = make_user('nn_fund', 'nn_fund_management.group_fund_user')
        cls.user_finance = make_user(
            'nn_finance', 'nn_fund_management.group_finance_user')
        cls.user_gm = make_user('nn_gm', 'nn_fund_management.group_gm_approver')
        cls.user_md = make_user('nn_md', 'nn_fund_management.group_md_approver')
        cls.user_admin = make_user(
            'nn_admin', 'nn_fund_management.group_fund_admin')

        cls.account = cls.env['nn.fund.account'].create({
            'name': 'Main Account', 'account_type': 'bank'})
        cls.project_a = cls.env['nn.project'].create({'name': 'Project A'})
        cls.project_b = cls.env['nn.project'].create({'name': 'Project B'})
        cls.expense = cls.env['nn.expense.head'].create({'name': 'Rent'})

    # -- helpers -------------------------------------------------------
    def _receive(self, amount, ref='IN-1'):
        inf = self.env['nn.incoming.fund'].with_user(self.user_finance).create({
            'fund_account_id': self.account.id,
            'amount': amount,
            'transaction_reference': ref,
        })
        inf.action_confirm()
        return inf

    def _allocate(self, amount, project=None, approve=True):
        project = project or self.project_a
        alloc = self.env['nn.fund.allocation'].with_user(self.user_fund).create({
            'fund_account_id': self.account.id,
            'target_type': 'project',
            'project_id': project.id,
            'amount': amount,
        })
        alloc.action_submit()
        if approve:
            alloc.with_user(self.user_gm).approve()
            alloc.with_user(self.user_md).approve()
        return alloc


class TestIncomingFund(TestFundManagementCommon):

    def test_confirm_increases_available(self):
        self._receive(1000000)
        self.assertEqual(self.account.total_received, 1000000)
        self.assertEqual(self.account.available_balance, 1000000)

    def test_duplicate_reference_blocked(self):
        self._receive(100, ref='DUP')
        with self.assertRaises(Exception):
            # Same reference in the same account -> DB unique constraint.
            self.env['nn.incoming.fund'].with_user(self.user_finance).create({
                'fund_account_id': self.account.id,
                'amount': 200, 'transaction_reference': 'DUP',
            }).action_confirm()

    def test_confirm_is_finance_only(self):
        inf = self.env['nn.incoming.fund'].with_user(self.user_finance).create({
            'fund_account_id': self.account.id,
            'amount': 100, 'transaction_reference': 'FIN-1'})
        with self.assertRaises(AccessError):
            inf.with_user(self.user_fund).action_confirm()


class TestAllocation(TestFundManagementCommon):

    def test_hold_then_reject_returns(self):
        self._receive(1000000)
        alloc = self._allocate(600000, approve=False)
        self.assertEqual(self.account.on_hold_amount, 600000)
        self.assertEqual(self.account.available_balance, 400000)
        alloc.with_user(self.user_gm).reject('no')
        self.assertEqual(self.account.on_hold_amount, 0)
        self.assertEqual(self.account.available_balance, 1000000)

    def test_approve_assigns(self):
        self._receive(1000000)
        self._allocate(600000)
        self.assertEqual(self.account.assigned_amount, 600000)
        self.assertEqual(self.account.available_balance, 400000)
        self.assertEqual(self.project_a.total_allocated, 600000)

    def test_over_allocation_blocked(self):
        self._receive(500000)
        alloc = self.env['nn.fund.allocation'].with_user(self.user_fund).create({
            'fund_account_id': self.account.id, 'target_type': 'project',
            'project_id': self.project_a.id, 'amount': 600000})
        with self.assertRaises(UserError):
            alloc.action_submit()

    def test_project_and_expense_mutually_exclusive(self):
        with self.assertRaises(ValidationError):
            self.env['nn.fund.allocation'].create({
                'fund_account_id': self.account.id, 'target_type': 'project',
                'project_id': self.project_a.id,
                'expense_head_id': self.expense.id, 'amount': 1})


class TestApprovalRules(TestFundManagementCommon):

    def test_md_cannot_approve_before_gm(self):
        self._receive(1000000)
        alloc = self._allocate(100000, approve=False)
        with self.assertRaises(AccessError):
            alloc.with_user(self.user_md).approve()

    def test_only_approver_group_can_approve(self):
        self._receive(1000000)
        alloc = self._allocate(100000, approve=False)
        with self.assertRaises(AccessError):
            alloc.with_user(self.user_fund).approve()

    def test_self_approval_blocked(self):
        self._receive(1000000)
        # GM creates and submits the request, then tries to approve it.
        alloc = self.env['nn.fund.allocation'].with_user(self.user_gm).create({
            'fund_account_id': self.account.id, 'target_type': 'project',
            'project_id': self.project_a.id, 'amount': 100000})
        alloc.action_submit()
        with self.assertRaises(UserError):
            alloc.with_user(self.user_gm).approve()

    def test_self_approval_allowed_when_configured(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'nn_fund_management.allow_self_approval', 'True')
        self._receive(1000000)
        alloc = self.env['nn.fund.allocation'].with_user(self.user_gm).create({
            'fund_account_id': self.account.id, 'target_type': 'project',
            'project_id': self.project_a.id, 'amount': 100000})
        alloc.action_submit()
        alloc.with_user(self.user_gm).approve()  # first step (GM)
        # Default rule has two steps, so after the GM step it is still pending.
        self.assertEqual(alloc.state, 'submitted')
        self.assertEqual(alloc.approval_step, 1)


class TestConfigurableRules(TestFundManagementCommon):

    def test_single_step_rule_approves_after_one_step(self):
        """A more specific rule (GM only, small amounts) is picked over the
        default and the request is fully approved after just the GM step."""
        rule = self.env['nn.approval.rule'].create({
            'name': 'Small (GM only)',
            'request_type': 'allocation',
            'sequence': 1,  # more specific than the default (100)
            'amount_min': 0,
            'amount_max': 50000,
            'step_ids': [(0, 0, {
                'name': 'General Manager', 'sequence': 10,
                'group_id': self.env.ref(
                    'nn_fund_management.group_gm_approver').id})],
        })
        self._receive(1000000)
        alloc = self.env['nn.fund.allocation'].with_user(self.user_fund).create({
            'fund_account_id': self.account.id, 'target_type': 'project',
            'project_id': self.project_a.id, 'amount': 40000})
        alloc.action_submit()
        self.assertEqual(alloc.approval_rule_id, rule)
        alloc.with_user(self.user_gm).approve()  # single step => approved
        self.assertEqual(alloc.state, 'approved')
        self.assertEqual(self.account.assigned_amount, 40000)

    def test_large_amount_uses_default_two_step_rule(self):
        self.env['nn.approval.rule'].create({
            'name': 'Small (GM only)', 'request_type': 'allocation',
            'sequence': 1, 'amount_min': 0, 'amount_max': 50000,
            'step_ids': [(0, 0, {
                'name': 'GM', 'sequence': 10,
                'group_id': self.env.ref(
                    'nn_fund_management.group_gm_approver').id})],
        })
        self._receive(1000000)
        alloc = self.env['nn.fund.allocation'].with_user(self.user_fund).create({
            'fund_account_id': self.account.id, 'target_type': 'project',
            'project_id': self.project_a.id, 'amount': 300000})
        alloc.action_submit()
        # Above the small-rule ceiling, so it falls back to the default rule.
        self.assertEqual(alloc.approval_rule_id.step_count, 2)
        alloc.with_user(self.user_gm).approve()
        self.assertEqual(alloc.state, 'submitted')  # still needs MD
        alloc.with_user(self.user_md).approve()
        self.assertEqual(alloc.state, 'approved')

    def test_repeated_approval_no_double_movement(self):
        self._receive(1000000)
        alloc = self._allocate(600000)  # fully approved
        self.assertEqual(self.account.assigned_amount, 600000)
        # Acting again on an approved request must not move money twice.
        with self.assertRaises(UserError):
            alloc.with_user(self.user_md).approve()
        self.assertEqual(self.account.assigned_amount, 600000)
        self.assertEqual(self.account.available_balance, 400000)


class TestRequisition(TestFundManagementCommon):

    def _approved_requisition(self, amount):
        req = self.env['nn.fund.requisition'].with_user(self.user_fund).create({
            'target_type': 'project', 'project_id': self.project_a.id,
            'amount': amount})
        req.action_submit()
        req.with_user(self.user_gm).approve()
        req.with_user(self.user_md).approve()
        return req

    def test_hold_and_approve(self):
        self._receive(1000000)
        self._allocate(600000)
        req = self.env['nn.fund.requisition'].with_user(self.user_fund).create({
            'target_type': 'project', 'project_id': self.project_a.id,
            'amount': 150000})
        req.action_submit()
        self.assertEqual(self.project_a.requisition_hold, 150000)
        self.assertEqual(self.project_a.available_fund, 450000)
        req.with_user(self.user_gm).approve()
        req.with_user(self.user_md).approve()
        self.assertEqual(self.project_a.approved_unspent, 150000)
        self.assertEqual(req.remaining_billable, 150000)

    def test_over_requisition_blocked(self):
        self._receive(1000000)
        self._allocate(100000)
        req = self.env['nn.fund.requisition'].with_user(self.user_fund).create({
            'target_type': 'project', 'project_id': self.project_a.id,
            'amount': 200000})
        with self.assertRaises(UserError):
            req.action_submit()

    def test_close_releases_unused(self):
        self._receive(1000000)
        self._allocate(600000)
        req = self._approved_requisition(150000)
        req.action_close()
        self.assertEqual(req.state, 'closed')
        self.assertEqual(self.project_a.approved_unspent, 0)
        self.assertEqual(self.project_a.available_fund, 600000)


class TestBill(TestFundManagementCommon):

    def _setup_requisition(self, alloc=600000, req=150000):
        self._receive(1000000)
        self._allocate(alloc)
        r = self.env['nn.fund.requisition'].with_user(self.user_fund).create({
            'target_type': 'project', 'project_id': self.project_a.id,
            'amount': req})
        r.action_submit()
        r.with_user(self.user_gm).approve()
        r.with_user(self.user_md).approve()
        return r

    def test_partial_bill_and_remaining(self):
        req = self._setup_requisition()
        bill = self.env['nn.bill'].with_user(self.user_fund).create({
            'requisition_id': req.id, 'amount': 100000,
            'target_type': 'project', 'project_id': self.project_a.id})
        bill.action_post()
        self.assertEqual(req.remaining_billable, 50000)
        self.assertEqual(self.project_a.total_spent, 100000)

    def test_over_bill_blocked(self):
        req = self._setup_requisition()
        b1 = self.env['nn.bill'].with_user(self.user_fund).create({
            'requisition_id': req.id, 'amount': 100000,
            'target_type': 'project', 'project_id': self.project_a.id})
        b1.action_post()
        b2 = self.env['nn.bill'].with_user(self.user_fund).create({
            'requisition_id': req.id, 'amount': 60000,
            'target_type': 'project', 'project_id': self.project_a.id})
        with self.assertRaises(UserError):
            b2.action_post()

    def test_cross_target_bill_blocked(self):
        req = self._setup_requisition()
        with self.assertRaises(ValidationError):
            self.env['nn.bill'].with_user(self.user_fund).create({
                'requisition_id': req.id, 'amount': 1000,
                'target_type': 'project', 'project_id': self.project_b.id})

    def test_reversal_restores_without_creating_funds(self):
        req = self._setup_requisition()
        bill = self.env['nn.bill'].with_user(self.user_fund).create({
            'requisition_id': req.id, 'amount': 100000,
            'target_type': 'project', 'project_id': self.project_a.id})
        bill.action_post()
        bill.action_cancel()
        self.assertEqual(req.remaining_billable, 150000)
        self.assertEqual(self.project_a.total_spent, 0)

    def test_cannot_edit_posted_bill(self):
        req = self._setup_requisition()
        bill = self.env['nn.bill'].with_user(self.user_fund).create({
            'requisition_id': req.id, 'amount': 100000,
            'target_type': 'project', 'project_id': self.project_a.id})
        bill.action_post()
        with self.assertRaises(UserError):
            bill.write({'amount': 1})

    def test_bill_against_non_approved_requisition_blocked(self):
        self._receive(1000000)
        self._allocate(600000)
        req = self.env['nn.fund.requisition'].with_user(self.user_fund).create({
            'target_type': 'project', 'project_id': self.project_a.id,
            'amount': 100000})  # left in draft, never approved
        bill = self.env['nn.bill'].with_user(self.user_fund).create({
            'requisition_id': req.id, 'amount': 1000,
            'target_type': 'project', 'project_id': self.project_a.id})
        with self.assertRaises(UserError):
            bill.action_post()


class TestErrorHandling(TestFundManagementCommon):
    """Server-side guards and edge cases."""

    def test_cannot_edit_amount_after_submit(self):
        self._receive(1000000)
        alloc = self._allocate(100000, approve=False)  # submitted
        with self.assertRaises(UserError):
            alloc.write({'amount': 200000})

    def test_reset_to_draft_then_edit_allowed(self):
        self._receive(1000000)
        alloc = self._allocate(100000, approve=False)
        alloc.with_user(self.user_gm).reject('not now')
        alloc.action_reset_to_draft()
        alloc.write({'amount': 50000})  # editable again in draft
        self.assertEqual(alloc.amount, 50000)

    def test_submit_twice_blocked(self):
        self._receive(1000000)
        alloc = self._allocate(100000, approve=False)
        with self.assertRaises(UserError):
            alloc.action_submit()

    def test_reject_requires_comment(self):
        self._receive(1000000)
        alloc = self._allocate(100000, approve=False)
        with self.assertRaises(UserError):
            alloc.with_user(self.user_gm).reject('')

    def test_cancel_approved_requires_admin(self):
        self._receive(1000000)
        alloc = self._allocate(100000)  # approved
        with self.assertRaises(AccessError):
            alloc.with_user(self.user_fund).action_cancel()
        alloc.with_user(self.user_admin).action_cancel()
        self.assertEqual(alloc.state, 'cancelled')
        # Money returned to the account after cancelling the approved request.
        self.assertEqual(self.account.assigned_amount, 0)
        self.assertEqual(self.account.available_balance, 1000000)

    def test_cannot_edit_confirmed_incoming_fund(self):
        inf = self._receive(100, ref='LOCK-1')
        with self.assertRaises(UserError):
            inf.write({'amount': 999})

    def test_cannot_delete_confirmed_incoming_fund(self):
        inf = self._receive(100, ref='LOCK-2')
        with self.assertRaises(UserError):
            inf.unlink()

    def test_cannot_delete_submitted_allocation(self):
        self._receive(1000000)
        alloc = self._allocate(100000, approve=False)
        with self.assertRaises(UserError):
            alloc.unlink()

    def test_close_only_from_approved(self):
        req = self.env['nn.fund.requisition'].with_user(self.user_fund).create({
            'target_type': 'project', 'project_id': self.project_a.id,
            'amount': 100})  # draft
        with self.assertRaises(UserError):
            req.action_close()

    def test_submit_without_any_rule_is_blocked(self):
        # Deactivate every rule, then submitting must fail with a clear error.
        self.env['nn.approval.rule'].search([]).write({'active': False})
        self._receive(1000000)
        alloc = self.env['nn.fund.allocation'].with_user(self.user_fund).create({
            'fund_account_id': self.account.id, 'target_type': 'project',
            'project_id': self.project_a.id, 'amount': 1000})
        with self.assertRaises(UserError):
            alloc.action_submit()


class TestChat(TestFundManagementCommon):

    def test_open_chat_creates_channel_with_members(self):
        self._receive(1000000)
        alloc = self.env['nn.fund.allocation'].with_user(self.user_fund).create({
            'fund_account_id': self.account.id, 'target_type': 'project',
            'project_id': self.project_a.id, 'amount': 100000})
        action = alloc.with_user(self.user_fund).action_open_chat()
        self.assertTrue(alloc.channel_id)
        self.assertEqual(action['tag'], 'mail.action_discuss')
        self.assertEqual(action['context']['active_id'], alloc.channel_id.id)
        members = alloc.channel_id.channel_member_ids.mapped('partner_id')
        # Requester and the GM/MD approvers are in the discussion.
        self.assertIn(self.user_fund.partner_id, members)
        self.assertIn(self.user_gm.partner_id, members)
        self.assertIn(self.user_md.partner_id, members)

    def test_open_chat_is_idempotent(self):
        self._receive(1000000)
        alloc = self.env['nn.fund.allocation'].create({
            'fund_account_id': self.account.id, 'target_type': 'project',
            'project_id': self.project_a.id, 'amount': 100000})
        alloc.action_open_chat()
        channel = alloc.channel_id
        alloc.action_open_chat()
        self.assertEqual(alloc.channel_id, channel)  # same channel reused


class TestBankEmail(TestFundManagementCommon):

    SAMPLE = ("You have received BDT 1,000,000.00 in account XXXX1234 from "
              "John Doe. TrxID: BNK999 on 2026-06-18. - ABC Bank")

    def test_parse_creates_pending_incoming_fund(self):
        be = self.env['nn.bank.email'].create({
            'name': 'Credit Alert', 'raw_body': self.SAMPLE,
            'message_id': '<msg-1@bank>',
            'fund_account_id': self.account.id})
        be.action_parse()
        self.assertEqual(be.state, 'parsed')
        self.assertEqual(be.amount, 1000000)
        self.assertEqual(be.transaction_reference, 'BNK999')
        self.assertTrue(be.incoming_fund_id)
        self.assertEqual(be.incoming_fund_id.state, 'pending_verification')
        self.assertEqual(be.incoming_fund_id.amount, 1000000)

    def test_duplicate_reference_detected(self):
        self.env['nn.incoming.fund'].create({
            'fund_account_id': self.account.id, 'amount': 10,
            'transaction_reference': 'BNK999'})
        be = self.env['nn.bank.email'].create({
            'name': 'Credit', 'raw_body': self.SAMPLE,
            'message_id': '<msg-2@bank>'})
        be.action_parse()
        self.assertEqual(be.state, 'failed')
        self.assertIn('Duplicate', be.error_log)

    def test_account_matched_by_number(self):
        self.account.account_number = '0099001234'  # ends with 1234
        be = self.env['nn.bank.email'].create({
            'name': 'Credit', 'raw_body': self.SAMPLE,
            'message_id': '<msg-match@bank>'})
        be.action_parse()
        self.assertEqual(be.state, 'parsed')
        self.assertEqual(be.incoming_fund_id.fund_account_id, self.account)

    def test_unmatched_without_default_is_flagged(self):
        be = self.env['nn.bank.email'].create({
            'name': 'Credit', 'raw_body': self.SAMPLE,
            'message_id': '<msg-nomatch@bank>'})
        be.action_parse()  # no account number match, no default configured
        self.assertEqual(be.state, 'failed')
        self.assertFalse(be.incoming_fund_id)

    def test_failed_parse_is_logged(self):
        be = self.env['nn.bank.email'].create({
            'name': 'Spam', 'raw_body': 'no money mentioned here',
            'message_id': '<msg-3@bank>'})
        be.action_parse()
        self.assertEqual(be.state, 'failed')
        self.assertTrue(be.error_log)

    def test_same_email_not_processed_twice(self):
        self.env['nn.bank.email'].create({
            'raw_body': 'x', 'message_id': '<dup@bank>'})
        with self.assertRaises(Exception):
            self.env['nn.bank.email'].create({
                'raw_body': 'y', 'message_id': '<dup@bank>'})
            self.env.flush_all()


class TestTransfer(TestFundManagementCommon):

    def test_hold_then_approve_moves(self):
        self._receive(1000000)
        self._allocate(600000, project=self.project_a)
        trf = self.env['nn.fund.transfer'].with_user(self.user_fund).create({
            'source_type': 'project', 'source_project_id': self.project_a.id,
            'dest_type': 'project', 'dest_project_id': self.project_b.id,
            'amount': 200000})
        trf.action_submit()
        self.assertEqual(self.project_a.transfer_hold, 200000)
        self.assertEqual(self.project_a.available_fund, 400000)
        self.assertEqual(self.project_b.available_fund, 0)
        trf.with_user(self.user_gm).approve()
        trf.with_user(self.user_md).approve()
        self.assertEqual(self.project_a.outgoing_transfer, 200000)
        self.assertEqual(self.project_b.incoming_transfer, 200000)
        self.assertEqual(self.project_b.available_fund, 200000)

    def test_over_transfer_blocked(self):
        self._receive(1000000)
        self._allocate(100000, project=self.project_a)
        trf = self.env['nn.fund.transfer'].with_user(self.user_fund).create({
            'source_type': 'project', 'source_project_id': self.project_a.id,
            'dest_type': 'project', 'dest_project_id': self.project_b.id,
            'amount': 200000})
        with self.assertRaises(UserError):
            trf.action_submit()

    def test_same_source_dest_blocked(self):
        self._receive(1000000)
        self._allocate(100000, project=self.project_a)
        with self.assertRaises(ValidationError):
            self.env['nn.fund.transfer'].with_user(self.user_fund).create({
                'source_type': 'project', 'source_project_id': self.project_a.id,
                'dest_type': 'project', 'dest_project_id': self.project_a.id,
                'amount': 1000})
