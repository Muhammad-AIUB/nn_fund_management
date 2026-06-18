# -*- coding: utf-8 -*-
from . import models
from . import wizard


def post_init_hook(env):
    """Grant the default admin user full module access on install.

    Done in Python (not XML data) because ``base.user_admin`` is flagged
    ``noupdate`` by the base module, so a data record cannot modify it.
    """
    admin = env.ref('base.user_admin', raise_if_not_found=False)
    group = env.ref('nn_fund_management.group_fund_admin',
                    raise_if_not_found=False)
    if admin and group:
        admin.write({'groups_id': [(4, group.id)]})
