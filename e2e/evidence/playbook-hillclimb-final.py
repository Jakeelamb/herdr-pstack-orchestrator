def lookup_reference(references, account):
    for key, value in references:
        if key == account:
            return value
    raise KeyError(account)


def reconcile_linear(references, payments):
    index = dict(reversed(references))
    return sum(index[account] * amount for account, amount in payments)
