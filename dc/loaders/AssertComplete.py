from dc.utils.ImportantVars import MONTHLY_VARS, WEEKLY_VARS


def assert_complete(dates, features, weekly=True):

    VARIABLES = WEEKLY_VARS if weekly else MONTHLY_VARS
    for v in VARIABLES:
        filt = [x for x in features if v in x]

        for d in dates:
            assert sum([d in x for x in filt]) > 0, '{}_{}.dat is not present.'.format(d, v)