from tj_common.utils import is_begin_transaction, is_end_transaction


def test_is_end_transaction_json_func():
    assert is_end_transaction('["Transaction","CommitTransaction"]')
    assert is_end_transaction("CommitTransaction")
    assert not is_begin_transaction('["Transaction","CommitTransaction"]')
    assert is_begin_transaction("BeginTransaction")
