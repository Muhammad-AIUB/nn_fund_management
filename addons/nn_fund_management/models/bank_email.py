# -*- coding: utf-8 -*-
import logging
import re

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BankEmail(models.Model):
    """Prototype: turn bank transaction-notification emails into incoming funds.

    An email can arrive two ways:

    * **Mail gateway** - point a mail alias (data: ``bank-funds``) at this model
      so Odoo's incoming-mail routing creates a record per email.
    * **Manual paste** - create a record, paste the email body, click *Parse*
      (handy for the demo without a live mail server).

    Safeguards required by the brief:

    * the same email is never processed twice (``message_id`` is unique);
    * duplicate transaction references are detected and flagged;
    * parsing failures are logged on the record (``error_log``) and to the
      server log, never raised to the gateway;
    * email-created funds land in **Pending Verification**, to be confirmed by
      Finance;
    * no bank credentials live in the code - this only parses received text.
    """
    _name = 'nn.bank.email'
    _description = 'Bank Notification Email'
    _inherit = ['mail.thread']
    _order = 'received_date desc, id desc'

    name = fields.Char(string='Subject', default='Bank Email')
    message_id = fields.Char(string='Email Message-ID', copy=False, index=True)
    email_from = fields.Char(string='From')
    raw_body = fields.Text(string='Email Body')
    received_date = fields.Datetime(
        string='Received', default=fields.Datetime.now)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company)

    state = fields.Selection(
        selection=[
            ('received', 'Received'),
            ('parsed', 'Parsed'),
            ('failed', 'Failed'),
        ], default='received', required=True, tracking=True)
    error_log = fields.Text(string='Error Log', readonly=True)

    # Parsed fields
    bank_name = fields.Char(readonly=True)
    bank_account = fields.Char(string='Account (masked)', readonly=True)
    transaction_reference = fields.Char(readonly=True)
    transaction_date = fields.Date(readonly=True)
    amount = fields.Monetary(readonly=True)
    sender_info = fields.Char(string='Sender', readonly=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    fund_account_id = fields.Many2one(
        'nn.fund.account', string='Target Fund Account',
        help="Account the created incoming fund is booked to. Auto-matched "
             "from the parsed account number when possible.")
    incoming_fund_id = fields.Many2one(
        'nn.incoming.fund', string='Created Incoming Fund', readonly=True,
        copy=False)

    _sql_constraints = [
        ('unique_message_id', 'unique(message_id)',
         'This email (message-id) has already been imported.'),
    ]

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _extract_fields(self, text, subject=''):
        """Heuristic parser for a bank notification. Returns a dict of values.

        Tuned for messages such as:
            "You have received BDT 1,000,000.00 in account XXXX1234 from
             John Doe. TrxID: BNK123456 on 2026-06-18. - ABC Bank"
        Real banks vary; patterns are documented as an assumption in README.
        """
        blob = '%s\n%s' % (subject or '', text or '')

        amount_match = re.search(
            r'(?:BDT|TK\.?|৳|USD|\$)\s*([\d,]+(?:\.\d+)?)', blob, re.I)
        if not amount_match:
            raise UserError(_("Could not find an amount in the email."))
        amount = float(amount_match.group(1).replace(',', ''))

        ref_match = re.search(
            r'(?:Trx\s*ID|TrxID|Reference|Ref|Transaction\s*(?:ID|Ref))'
            r'\s*[:#]?\s*([A-Za-z0-9\-]+)', blob, re.I)
        account_match = re.search(
            r'(?:account|a/?c|acc(?:ount)?\s*no)\s*[:#]?\s*'
            r'([X\*\d]{4,})', blob, re.I)
        bank_match = re.search(r'([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*\sBank)',
                               blob)
        sender_match = re.search(
            r'from\s+([A-Za-z][A-Za-z .]+?)(?:\.|,|\s+TrxID|\s+on\b|$)',
            blob, re.I)
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', blob)

        return {
            'amount': amount,
            'transaction_reference': (ref_match.group(1)
                                      if ref_match else False),
            'bank_account': account_match.group(1) if account_match else False,
            'bank_name': bank_match.group(1).strip() if bank_match else False,
            'sender_info': (sender_match.group(1).strip()
                            if sender_match else False),
            'transaction_date': date_match.group(1) if date_match else False,
        }

    def _is_duplicate_reference(self, reference):
        if not reference:
            return False
        Incoming = self.env['nn.incoming.fund']
        return bool(Incoming.search_count(
            [('transaction_reference', '=', reference)]))

    def _find_fund_account(self, data):
        """Resolve the target account without guessing:
        1. match the parsed account number, else
        2. the account chosen on this email, else
        3. the configured default bank-email account.
        Returns an empty recordset if none apply (caller flags the email)."""
        Account = self.env['nn.fund.account']
        acc_str = (data.get('bank_account') or '')
        digits = ''.join(ch for ch in acc_str if ch.isdigit())[-4:]
        if digits:
            acc = Account.search(
                [('account_number', 'ilike', digits)], limit=1)
            if acc:
                return acc
        if self.fund_account_id:
            return self.fund_account_id
        default_id = self.env['ir.config_parameter'].sudo().get_param(
            'nn_fund_management.bank_default_account_id')
        if default_id:
            return Account.browse(int(default_id)).exists()
        return Account

    def action_parse(self):
        for rec in self:
            try:
                data = rec._extract_fields(rec.raw_body, rec.name)
                ref = data.get('transaction_reference')
                if rec._is_duplicate_reference(ref):
                    rec.write({
                        'state': 'failed',
                        'error_log': _(
                            "Duplicate transaction reference: %s", ref),
                        **{k: v for k, v in data.items() if k != 'amount'},
                        'amount': data['amount'],
                    })
                    _logger.warning("Bank email %s: duplicate reference %s",
                                    rec.id, ref)
                    continue
                account = rec._find_fund_account(data)
                if not account:
                    raise UserError(_(
                        "Could not match a fund account for this email. Set "
                        "the account number on the email, or configure a "
                        "default bank-email account in the module settings."))
                fund = self.env['nn.incoming.fund'].create({
                    'fund_account_id': account.id,
                    'amount': data['amount'],
                    'transaction_reference':
                        ref or 'BANK-%s' % (rec.message_id or rec.id),
                    'source': data.get('sender_info') or rec.email_from,
                    'date': data.get('transaction_date')
                    or fields.Date.context_today(rec),
                    'description': _(
                        "Imported from bank email. Bank: %(bank)s, "
                        "A/C: %(acc)s",
                        bank=data.get('bank_name') or '-',
                        acc=data.get('bank_account') or '-'),
                    'state': 'pending_verification',
                    'source_email_id': rec.id,
                })
                rec.write({
                    'state': 'parsed',
                    'incoming_fund_id': fund.id,
                    'error_log': False,
                    **data,
                })
            except Exception as exc:  # noqa: BLE001 - log, never crash gateway
                rec.write({'state': 'failed', 'error_log': str(exc)})
                _logger.exception("Failed to parse bank email %s", rec.id)
        return True

    # ------------------------------------------------------------------
    # Mail gateway
    # ------------------------------------------------------------------
    @api.model
    def message_new(self, msg_dict, custom_values=None):
        message_id = msg_dict.get('message_id')
        if message_id:
            existing = self.search(
                [('message_id', '=', message_id)], limit=1)
            if existing:
                # Same email cannot be processed twice.
                return existing
        values = dict(custom_values or {})
        values.update({
            'name': msg_dict.get('subject') or 'Bank Email',
            'message_id': message_id,
            'email_from': msg_dict.get('email_from'),
            'raw_body': tools.html2plaintext(msg_dict.get('body') or ''),
        })
        record = super().message_new(msg_dict, custom_values=values)
        record.action_parse()
        return record
