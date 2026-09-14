from app.spending_classification import classify_outflow


class Row(dict):
    def __getitem__(self, key):
        return super().get(key)


def test_services_numeriques_is_fixed_not_variable():
    row = Row(
        category='Services numériques',
        transaction_type='expense',
        is_internal_transfer=0,
        label='APPLE.COM/BILL',
    )
    assert classify_outflow(row, set()) == 'fixed'


def test_refund_category_is_excluded_not_variable():
    row = Row(
        category='Remboursement',
        transaction_type='expense',
        is_internal_transfer=0,
        label='REMBOURSEMENT',
    )
    assert classify_outflow(row, set()) == 'excluded'


def test_restaurant_is_variable():
    row = Row(
        category='Restaurants',
        transaction_type='expense',
        is_internal_transfer=0,
        label='RESTAURANT',
    )
    assert classify_outflow(row, set()) == 'variable'


def test_navigo_is_fixed_even_with_transport_category():
    row = Row(
        category='Transport',
        transaction_type='expense',
        is_internal_transfer=0,
        label='PRLV NAVIGO',
    )
    assert classify_outflow(row, set()) == 'fixed'


def test_travel_is_non_routine():
    row = Row(
        category='Voyage',
        transaction_type='expense',
        is_internal_transfer=0,
        label='HOTEL',
    )
    assert classify_outflow(row, set()) == 'non_routine'
