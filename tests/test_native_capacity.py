import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_switcher as core
import quota
from test_capture_lifecycle import credential


def with_identity(wrapped=False):
    value={'token':{'refresh_token':'synthetic-refresh','access_token':'synthetic-access',
                    'token_type':'Bearer','expiry':'2026-10-09T12:00:00Z','id_token':'x'*2600}}
    raw=json.dumps(value).encode()
    if wrapped:
        raw=b'go-keyring-base64:'+base64.b64encode(raw)
    return dict(credential('A'),blob=base64.b64encode(raw).decode())


class NativeCapacityTests(unittest.TestCase):
    def test_oversized_old_snapshot_is_adapted_without_changing_grants_or_original(self):
        original=with_identity()
        untouched=copy.deepcopy(original)
        adapted=core.prepare_native_record(original)
        self.assertLessEqual(len(base64.b64decode(adapted['blob'])),core.MAX_NATIVE_BLOB)
        self.assertEqual(original,untouched)
        before=quota.decode(original)[1]
        after=quota.decode(adapted)[1]
        self.assertNotIn('id_token',after)
        self.assertEqual(after,{k:v for k,v in before.items() if k!='id_token'})
        self.assertEqual({k:v for k,v in adapted.items() if k!='blob'}, {k:v for k,v in original.items() if k!='blob'})

    def test_wrapped_snapshot_keeps_official_wrapper(self):
        adapted=core.prepare_native_record(with_identity(True))
        self.assertLessEqual(len(base64.b64decode(adapted['blob'])),core.MAX_NATIVE_BLOB)
        self.assertTrue(quota.decode(adapted)[2])
        self.assertEqual(core.refresh_identity(adapted),'synthetic-refresh')

    def test_small_native_record_is_unchanged(self):
        original=credential('A')
        self.assertIs(core.prepare_native_record(original),original)

    def test_compaction_keeps_optional_fields_when_already_sufficient(self):
        original=dict(credential('A'))
        value={'refresh_token':'synthetic-refresh','id_token':'optional-small'}
        raw=json.dumps(value).encode()+b' '*3000
        original['blob']=base64.b64encode(raw).decode()
        adapted=core.prepare_native_record(original)
        self.assertEqual(quota.decode(adapted)[1],value)

    def test_irreducible_oversize_aborts_before_closing_or_writing(self):
        original=with_identity()
        value=quota.decode(original)[0]
        value['token']['access_token']='x'*2700
        value['token'].pop('id_token')
        original['blob']=base64.b64encode(json.dumps(value).encode()).decode()
        class Vault:
            def load(self, _): return {'label':'Synthetic','credential':original}
        with patch.object(core,'close_antigravity') as close:
            store=unittest.mock.Mock()
            switcher=core.Switcher(store,Vault())
            with self.assertRaises(core.LocalError):
                switcher.switch('synthetic.agprofile')
            close.assert_not_called()
            store.write.assert_not_called()

    def test_native_write_checks_capacity_before_calling_windows(self):
        store=core.NativeStore.__new__(core.NativeStore)
        store.api=unittest.mock.Mock()
        with self.assertRaisesRegex(core.LocalError,'2560'):
            store.write(with_identity())
        store.api.CredWriteW.assert_not_called()

    def test_refresh_does_not_persist_returned_identity_token(self):
        original=with_identity()
        with patch.object(quota,'local_client_config',return_value=('synthetic-client','synthetic-config')):
            refreshed=quota.renew(original,lambda *a,**k:{'access_token':'synthetic-new','expires_in':3600,'id_token':'x'*4000})
        token=quota.decode(refreshed)[1]
        self.assertNotIn('id_token',token)
        self.assertEqual(token['refresh_token'],'synthetic-refresh')
        self.assertEqual(token['access_token'],'synthetic-new')
        self.assertLessEqual(len(base64.b64decode(refreshed['blob'])),core.MAX_NATIVE_BLOB)

    def test_rollback_keeps_native_error_code_for_diagnostics(self):
        previous=credential('A')
        target=credential('B')
        class Store:
            value=previous
            def write(self, record):
                if record==target: raise core.NativeError('synthetic failure',1783)
                self.value=record
            def read(self): return self.value
        store=Store()
        with self.assertRaises(core.NativeError) as captured:
            core.replace_verified(store,target,previous)
        self.assertEqual(captured.exception.code,1783)
        self.assertIn('1783',str(captured.exception))
        self.assertIn('已恢复',str(captured.exception))
        self.assertEqual(store.read(),previous)
